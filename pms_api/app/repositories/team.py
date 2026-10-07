"""Project teams and resource allocation.

A person is identified by their login user id when known, otherwise by name (case-insensitive), so the same
person on two projects is recognised as one resource for the allocation rules and the Resources screens."""
from datetime import date

from sqlalchemy import case, func, or_, text
from sqlalchemy.orm import Session

from app.models.projects import Project
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.models.timesheets import TimeEntry
from app.schemas.team import member_out
from app.core.access import project_scope
from app.core.industries import PM_ROLE

# Projects in these states no longer hold people's time.
INACTIVE_PROJECT_STATUSES = ("Closed",)


class TeamError(Exception):
    """A team rule was broken; the message is safe to show to the user."""


def _company_members(db: Session, principal):
    """Every live team row of the company, whatever projects the caller can see: a person's time is one
    budget, so the allocation rules always count all of it."""
    return (
        db.query(ProjectMember)
        .join(Project, Project.id == ProjectMember.project_id)
        .filter(ProjectMember.client_id == principal.client_id, ProjectMember.is_deleted == False, Project.is_deleted == False)  # noqa: E712
    )


def _live_members(db: Session, principal):
    return _company_members(db, principal).filter(project_scope(db, principal))


def _lock_team(db, principal) -> None:
    """Holds the company's team lock until commit, so two people adding or changing members at the same
    moment are checked one after the other (no duplicate rows, nobody booked over 100%)."""
    db.execute(
        text("EXEC sp_getapplock @Resource = :r, @LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 15000"),
        {"r": f"pms_team_{principal.client_id}"},
    )


def _same_person(user_id, name):
    by_name = func.lower(ProjectMember.member_name) == (name or "").lower()
    return or_(ProjectMember.user_id == user_id, by_name) if user_id else by_name


def _assigned_to(member):
    """Tasks of the member's project assigned to them (by user id when known, else by name)."""
    by_name = func.lower(Task.assignee_name) == member.member_name.lower()
    who = or_(Task.assignee_id == member.user_id, by_name) if member.user_id else by_name
    return (Task.project_id == member.project_id) & (Task.is_deleted == False) & who  # noqa: E712


def get_member(db, principal, project_id, member_id):
    return _live_members(db, principal).filter(ProjectMember.project_id == project_id, ProjectMember.id == member_id).one_or_none()


def _task_stats(db: Session, members) -> dict:
    today = date.today()
    stats = {}
    for m in members:
        open_, done, overdue = db.query(
            func.sum(case((Task.status != "Done", 1), else_=0)),
            func.sum(case((Task.status == "Done", 1), else_=0)),
            func.sum(case(((Task.status != "Done") & (Task.due_date < today), 1), else_=0)),
        ).filter(_assigned_to(m)).one()
        stats[m.id] = {"open": int(open_ or 0), "done": int(done or 0), "overdue": int(overdue or 0)}
    return stats


def list_members(db, principal, project_id) -> list:
    members = (
        _live_members(db, principal)
        .filter(ProjectMember.project_id == project_id)
        .order_by(case((ProjectMember.role == "Project Manager", 0), else_=1), ProjectMember.member_name)
        .all()
    )
    stats = _task_stats(db, members)
    return [member_out(m, stats.get(m.id)) for m in members]


def _other_allocations(db, principal, user_id, name, exclude_member_id=None):
    """The person's time already promised to other active projects, company-wide: [(project_id, project_code, pct), ...]."""
    query = (
        _company_members(db, principal)
        .filter(_same_person(user_id, name), Project.status.notin_(INACTIVE_PROJECT_STATUSES))
        .with_entities(Project.id, Project.project_code, ProjectMember.allocation_pct, ProjectMember.id)
    )
    return [(pid, code, pct) for pid, code, pct, mid in query if mid != exclude_member_id]


def _check_allocation(db, principal, data, exclude_member_id=None):
    others = _other_allocations(db, principal, data.get("user_id"), data["member_name"], exclude_member_id)
    used = sum(pct for _, _, pct in others)
    if used + data["allocation_pct"] > 100:
        free = max(0, 100 - used)
        # Projects the caller cannot see are summed up without their codes.
        ids = {pid for pid, _, _ in others}
        visible = {pid for (pid,) in db.query(Project.id).filter(Project.id.in_(ids), project_scope(db, principal))} if ids else set()
        parts = [f"{code} {pct}%" for pid, code, pct in others if pid in visible]
        hidden = sum(pct for pid, _, pct in others if pid not in visible)
        if hidden:
            parts.append(f"{hidden}% on other projects")
        raise TeamError(f"{data['member_name']} is already {used}% allocated ({', '.join(parts)}). At most {free}% is free.")


def _check_duplicate(db, principal, project_id, data, exclude_member_id=None):
    query = _company_members(db, principal).filter(ProjectMember.project_id == project_id, _same_person(data.get("user_id"), data["member_name"]))
    if exclude_member_id:
        query = query.filter(ProjectMember.id != exclude_member_id)
    if query.first():
        raise TeamError(f"{data['member_name']} is already in this project's team")


def _check_dates(project, data):
    start, end = data.get("start_date"), data.get("end_date")
    if start and project.start_date and start < project.start_date:
        raise TeamError("A member cannot start before the project starts")
    if end and project.end_date and end > project.end_date:
        raise TeamError("A member cannot stay after the project ends")


def _check_role(db, principal, role, current=None):
    """The role must be one of the company's roles (Settings > Industry); a member keeps an older role as is."""
    from app.repositories.settings import company_roles

    if role != current and role not in company_roles(db, principal.client_id):
        raise TeamError(f"'{role}' is not one of your company's team roles. Add it in Settings > Industry & Roles first")


def company_people(db, principal) -> list:
    """Internal login users of the company (never Client users) - the people a team member can be linked to."""
    from app.models.access import UserRole

    rows = (
        db.query(UserRole)
        .filter(UserRole.client_id == principal.client_id, UserRole.is_active == True, UserRole.role != "client")  # noqa: E712
        .order_by(UserRole.user_name)
        .all()
    )
    return [{"user_id": r.user_id, "name": r.user_name, "email": r.email, "role": r.role} for r in rows]


def _link_login(db, principal, data: dict) -> None:
    """Ties the member to their login user, which is what lets them log hours, see the project and (as Team Lead)
    approve the team's hours. Picked from the list = user_id sent; otherwise matched by email, then by exact name.
    A linked member always carries the login's own name and email."""
    people = company_people(db, principal)
    person = None
    if data.get("user_id"):
        person = next((p for p in people if p["user_id"] == data["user_id"]), None)
        if person is None:
            raise TeamError("That person is not an active user of your company. Pick them from the list")
    if person is None and data.get("email"):
        person = next((p for p in people if (p["email"] or "").lower() == data["email"].strip().lower()), None)
    if person is None:
        same_name = [p for p in people if p["name"].strip().lower() == data["member_name"].strip().lower()]
        person = same_name[0] if len(same_name) == 1 else None
    if person is not None:
        data["user_id"], data["member_name"] = person["user_id"], person["name"]
        data["email"] = person["email"] or data.get("email")


def _check_manager_role(project, data, current=None):
    """"Project Manager" belongs to the project's own manager (set on the project); anyone else given it would
    silently become "Other" on the next project save."""
    if data["role"] != PM_ROLE or current == PM_ROLE:
        return
    name = (project.project_manager_name or "").strip().lower()
    is_manager = bool(project.project_manager_id and data.get("user_id") == project.project_manager_id) or (
        bool(name) and data["member_name"].strip().lower() == name
    )
    if not is_manager:
        who = project.project_manager_name or "nobody yet"
        raise TeamError(f"'{PM_ROLE}' is the project's manager ({who}). Change the manager on the project itself, or pick another role")


def create_member(db, principal, project, data: dict) -> ProjectMember:
    _link_login(db, principal, data)
    _check_role(db, principal, data["role"])
    _check_manager_role(project, data)
    _lock_team(db, principal)
    _check_duplicate(db, principal, project.id, data)
    _check_dates(project, data)
    _check_allocation(db, principal, data)
    member = ProjectMember(**data, client_id=principal.client_id, project_id=project.id, created_by=principal.user_id, updated_by=principal.user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def update_member(db, principal, project, member: ProjectMember, data: dict) -> ProjectMember:
    _link_login(db, principal, data)
    _check_role(db, principal, data["role"], current=member.role)
    _check_manager_role(project, data, current=member.role)
    _lock_team(db, principal)
    _check_duplicate(db, principal, project.id, data, exclude_member_id=member.id)
    _check_dates(project, data)
    _check_allocation(db, principal, data, exclude_member_id=member.id)
    old_name = member.member_name
    # A renamed member keeps their tasks: tasks assigned by name follow the new name.
    if data["member_name"] != old_name:
        for task in db.query(Task).filter(_assigned_to(member)):
            task.assignee_name = data["member_name"]
    for key, value in data.items():
        setattr(member, key, value)
    member.updated_by = principal.user_id
    db.commit()
    db.refresh(member)
    return member


def remove_member(db, principal, member: ProjectMember) -> None:
    open_tasks = db.query(Task).filter(_assigned_to(member), Task.status != "Done").count()
    if open_tasks:
        raise TeamError(f"{member.member_name} still has {open_tasks} open task{'s' if open_tasks > 1 else ''} in this project. Reassign {'them' if open_tasks > 1 else 'it'} first.")
    member.is_deleted = True
    member.updated_by = principal.user_id
    db.commit()


def _has_work(db, member) -> bool:
    """True when the member has tasks, logged hours or planned time in this project."""
    if member.allocation_pct and float(member.allocation_pct) > 0:
        return True
    if db.query(Task.id).filter(Task.project_id == member.project_id, Task.is_deleted == False, _assigned_to(member)).first():  # noqa: E712
        return True
    return db.query(TimeEntry.id).filter(TimeEntry.member_id == member.id, TimeEntry.is_deleted == False).first() is not None  # noqa: E712


def ensure_manager_member(db, principal, project, commit=True) -> None:
    """Keeps exactly one "Project Manager" on the team: the project's current manager.

    The manager is added if missing (allocation 0% = not planned yet; editable in the Team tab) or given the
    Project Manager role if already on the team. A previous manager who was only added automatically is
    removed; one who has tasks, hours or planned time stays on the team as "Other", so history is kept."""
    if not project.project_manager_name:
        return
    members = _live_members(db, principal).filter(ProjectMember.project_id == project.id).all()
    pm_name = project.project_manager_name.lower()

    def is_manager(m):
        return bool(project.project_manager_id and m.user_id == project.project_manager_id) or (m.member_name or "").lower() == pm_name

    for m in members:
        if m.role == "Project Manager" and not is_manager(m):
            if _has_work(db, m):
                m.role = "Other"
            else:
                m.is_deleted = True
            m.updated_by = principal.user_id

    current = next((m for m in members if is_manager(m)), None)
    if current is not None:
        if current.role != "Project Manager":
            current.role = "Project Manager"
            current.updated_by = principal.user_id
        # Linked to the manager's login - unless another live member row already carries it (one row per login).
        if project.project_manager_id and not current.user_id and not any(m.user_id == project.project_manager_id for m in members):
            current.user_id = project.project_manager_id
    else:
        db.add(
            ProjectMember(
                client_id=principal.client_id,
                project_id=project.id,
                user_id=project.project_manager_id,
                member_name=project.project_manager_name,
                role="Project Manager",
                allocation_pct=0,
                created_by=principal.user_id,
                updated_by=principal.user_id,
            )
        )
    if commit:
        db.commit()


def resolve_assignee(db, principal, project_id, name, user_id):
    """Tasks can only be assigned to the project's team. Returns (user_id, member_name) of the matching member."""
    if not name and not user_id:
        return None, None
    member = _live_members(db, principal).filter(ProjectMember.project_id == project_id, _same_person(user_id, name)).first()
    if member is None:
        raise TeamError(f"{name or 'This person'} is not in this project's team. Add them in Project Details > Team first.")
    # The member's own login only: a member typed in by name (no login) never borrows the caller's user id.
    return member.user_id, member.member_name


def member_project_ids(db, principal, user_id) -> list:
    """Projects where the user is on the team - part of "My Projects"."""
    if not user_id:
        return []
    return [pid for (pid,) in _live_members(db, principal).filter(ProjectMember.user_id == user_id).with_entities(ProjectMember.project_id).distinct()]


def allocation_overview(db, principal, search=None, over_only=False) -> list:
    """Every person across the company's active projects, with their total allocation and workload.

    The search picks people (by name, or a role / project of theirs); each picked person's totals still count
    all their active projects. Totals also count projects the caller cannot see (shown as other_allocation)."""

    def key_of(m):
        return f"u{m.user_id}" if m.user_id else f"n{m.member_name.lower()}"

    active = Project.status.notin_(INACTIVE_PROJECT_STATUSES)
    rows = _live_members(db, principal).filter(active).with_entities(ProjectMember, Project.project_code, Project.project_name, Project.status).order_by(ProjectMember.member_name).all()
    if search:
        needle = search.strip().lower()
        matched = {key_of(m) for m, code, name, status in rows if any(needle in (v or "").lower() for v in (m.member_name, m.role, name))}
        rows = [row for row in rows if key_of(row[0]) in matched]
    company_total = {}
    for m in _company_members(db, principal).filter(active).with_entities(ProjectMember.user_id, ProjectMember.member_name, ProjectMember.allocation_pct):
        company_total[key_of(m)] = company_total.get(key_of(m), 0) + m.allocation_pct

    stats = _task_stats(db, [row[0] for row in rows])
    people = {}
    for m, code, name, status in rows:
        key = key_of(m)
        person = people.setdefault(
            key,
            {"key": key, "user_id": m.user_id, "member_name": m.member_name, "email": m.email, "total_allocation": 0,
             "open_tasks": 0, "overdue_tasks": 0, "done_tasks": 0, "roles": [], "projects": []},
        )
        s = stats.get(m.id, {})
        person["total_allocation"] += m.allocation_pct
        person["open_tasks"] += s.get("open", 0)
        person["overdue_tasks"] += s.get("overdue", 0)
        person["done_tasks"] += s.get("done", 0)
        person["email"] = person["email"] or m.email
        if m.role not in person["roles"]:
            person["roles"].append(m.role)
        person["projects"].append(
            {"member_id": m.id, "project_id": m.project_id, "project_code": code, "project_name": name, "project_status": status,
             "role": m.role, "allocation_pct": m.allocation_pct, "open_tasks": s.get("open", 0)}
        )
    for key, p in people.items():
        # Time on projects the caller cannot see still counts towards the person's load.
        p["other_allocation"] = max(0, company_total.get(key, 0) - p["total_allocation"])
        p["total_allocation"] += p["other_allocation"]
    result = sorted(people.values(), key=lambda p: (-p["total_allocation"], p["member_name"].lower()))
    for p in result:
        p["free_allocation"] = max(0, 100 - p["total_allocation"])
        p["load"] = "Full" if p["total_allocation"] >= 100 else "High" if p["total_allocation"] >= 80 else "Available"
    if over_only:
        result = [p for p in result if p["total_allocation"] >= 80]
    return result
