"""Industry presets: the team roles a company starts with and a starter project template per industry.

The PMS itself works the same in every industry (projects, tasks, approvals, money); what changes is the
words people use for their roles and the shape of a typical project. A company picks its industry in
Settings, can edit the role list, and can load the starter template into Project Templates.
"""
from app.models.team import MEMBER_ROLES

DEFAULT_INDUSTRY = "IT / Software"
PM_ROLE = "Project Manager"  # every role list keeps it: the project manager joins each team with this role

# Milestone: (name, due day). Task: (title, start day, duration days, milestone index).
INDUSTRIES = {
    "IT / Software": {
        "roles": MEMBER_ROLES,
        "template": {
            "name": "Website Development",
            "description": "Design, build, test and launch a website or web app",
            "duration_days": 30,
            "milestones": [("Design Approved", 9), ("Development Complete", 23), ("Go Live", 29)],
            "tasks": [
                ("Requirements workshop", 0, 2, 0),
                ("UI design", 2, 8, 0),
                ("Development", 10, 14, 1),
                ("Testing", 24, 4, 2),
                ("Deployment", 28, 2, 2),
            ],
        },
    },
    "Construction": {
        "roles": [PM_ROLE, "Site Engineer", "Site Supervisor", "Architect", "Civil Engineer", "Quantity Surveyor", "Safety Officer", "Contractor", "Other"],
        "template": {
            "name": "Building Construction",
            "description": "Site survey to handover of a building",
            "duration_days": 180,
            "milestones": [("Foundation Complete", 44), ("Structure Complete", 119), ("Handover", 179)],
            "tasks": [
                ("Site survey and soil test", 0, 7, 0),
                ("Excavation and foundation", 7, 38, 0),
                ("Columns, beams and slabs", 45, 75, 1),
                ("Plumbing and electrical", 120, 30, 2),
                ("Finishing and painting", 150, 25, 2),
                ("Final inspection and handover", 175, 5, 2),
            ],
        },
    },
    "Healthcare": {
        "roles": [PM_ROLE, "Doctor", "Nurse", "Lab Technician", "Pharmacist", "Hospital Administrator", "Quality And Compliance", "IT Support", "Other"],
        "template": {
            "name": "Clinic Setup",
            "description": "Licences, staff, equipment and opening of a clinic",
            "duration_days": 90,
            "milestones": [("Licences Approved", 29), ("Equipment Installed", 59), ("Clinic Opens", 89)],
            "tasks": [
                ("Apply for licences", 0, 30, 0),
                ("Hire doctors and staff", 10, 40, 1),
                ("Install medical equipment", 30, 30, 1),
                ("Staff training", 60, 15, 2),
                ("Trial run and audit", 75, 15, 2),
            ],
        },
    },
    "Manufacturing": {
        "roles": [PM_ROLE, "Production Engineer", "Quality Engineer", "Maintenance Engineer", "Shift Supervisor", "Procurement", "Operator", "Other"],
        "template": {
            "name": "New Production Line",
            "description": "Design, install and start a production line",
            "duration_days": 120,
            "milestones": [("Machines Installed", 59), ("Trial Production", 89), ("Line Live", 119)],
            "tasks": [
                ("Line layout design", 0, 15, 0),
                ("Procure machines", 15, 30, 0),
                ("Install and commission", 45, 15, 0),
                ("Trial runs and quality checks", 60, 30, 1),
                ("Operator training", 90, 15, 2),
                ("Start production", 105, 15, 2),
            ],
        },
    },
    "Consulting / Services": {
        "roles": [PM_ROLE, "Engagement Lead", "Consultant", "Analyst", "Designer", "Coordinator", "Other"],
        "template": {
            "name": "Consulting Engagement",
            "description": "Kick-off to final presentation of a client engagement",
            "duration_days": 60,
            "milestones": [("Kick-Off Done", 4), ("Findings Report", 39), ("Final Presentation", 59)],
            "tasks": [
                ("Kick-off meeting", 0, 2, 0),
                ("Current-state assessment", 2, 20, 1),
                ("Analysis and recommendations", 22, 18, 1),
                ("Draft report", 40, 10, 2),
                ("Final presentation", 50, 10, 2),
            ],
        },
    },
    "Marketing / Agency": {
        "roles": [PM_ROLE, "Account Manager", "Creative Director", "Copywriter", "Designer", "Social Media Manager", "Media Planner", "Other"],
        "template": {
            "name": "Marketing Campaign",
            "description": "Brief to launch and report of a marketing campaign",
            "duration_days": 45,
            "milestones": [("Creative Approved", 14), ("Campaign Live", 29), ("Results Report", 44)],
            "tasks": [
                ("Client brief and goals", 0, 3, 0),
                ("Concepts and copy", 3, 11, 0),
                ("Production of creatives", 15, 10, 1),
                ("Launch on channels", 25, 5, 1),
                ("Track and optimise", 30, 10, 2),
                ("Results report", 40, 5, 2),
            ],
        },
    },
    "Architecture / Interior Design": {
        "roles": [PM_ROLE, "Architect", "Interior Designer", "Draughtsman", "3D Visualiser", "Site Supervisor", "Vendor Coordinator", "Other"],
        "template": {
            "name": "Interior Fit-Out",
            "description": "Site measure to handover of an office or home interior",
            "duration_days": 75,
            "milestones": [("Design Approved", 19), ("Materials Ordered", 34), ("Handover", 74)],
            "tasks": [
                ("Site measurement", 0, 3, 0),
                ("Concept and 3D views", 3, 16, 0),
                ("Working drawings and BOQ", 20, 10, 1),
                ("Order materials", 30, 5, 1),
                ("Civil, carpentry and electrical", 35, 30, 2),
                ("Snag list and handover", 65, 10, 2),
            ],
        },
    },
    "Education / Training": {
        "roles": [PM_ROLE, "Instructional Designer", "Trainer", "Subject Expert", "Content Writer", "Coordinator", "Other"],
        "template": {
            "name": "Training Programme",
            "description": "Needs analysis to delivery and feedback of a course",
            "duration_days": 60,
            "milestones": [("Curriculum Approved", 14), ("Content Ready", 39), ("Batch Completed", 59)],
            "tasks": [
                ("Training needs analysis", 0, 7, 0),
                ("Curriculum design", 7, 7, 0),
                ("Content and assessments", 14, 25, 1),
                ("Trainer preparation", 35, 5, 1),
                ("Deliver sessions", 40, 15, 2),
                ("Feedback and certificates", 55, 5, 2),
            ],
        },
    },
    "Events": {
        "roles": [PM_ROLE, "Event Manager", "Logistics Coordinator", "Vendor Manager", "Designer", "Hospitality Lead", "Other"],
        "template": {
            "name": "Corporate Event",
            "description": "Planning to wrap-up of a conference or launch event",
            "duration_days": 40,
            "milestones": [("Venue Booked", 9), ("Vendors Confirmed", 24), ("Event Day", 37)],
            "tasks": [
                ("Event brief and budget", 0, 4, 0),
                ("Book venue", 4, 6, 0),
                ("Confirm vendors (AV, catering, decor)", 10, 15, 1),
                ("Invitations and registrations", 15, 20, 2),
                ("Rehearsal and set-up", 35, 2, 2),
                ("Event day and wrap-up", 37, 3, 2),
            ],
        },
    },
    "Real Estate": {
        "roles": [PM_ROLE, "Sales Manager", "Site Engineer", "Legal Advisor", "Marketing Executive", "CRM Executive", "Other"],
        "template": {
            "name": "Property Launch",
            "description": "Approvals, marketing and bookings for a new project",
            "duration_days": 90,
            "milestones": [("Approvals In Place", 29), ("Launch Event", 59), ("Bookings Target Met", 89)],
            "tasks": [
                ("RERA and legal approvals", 0, 30, 0),
                ("Brochure and sample flat", 20, 25, 1),
                ("Digital and channel marketing", 40, 30, 1),
                ("Launch event", 55, 5, 1),
                ("Site visits and bookings", 60, 30, 2),
            ],
        },
    },
    "Legal": {
        "roles": [PM_ROLE, "Partner", "Senior Associate", "Associate", "Paralegal", "Legal Secretary", "Other"],
        "template": {
            "name": "Legal Matter",
            "description": "Intake to closure of a client matter",
            "duration_days": 90,
            "milestones": [("Engagement Signed", 6), ("Filing Done", 44), ("Matter Closed", 89)],
            "tasks": [
                ("Client intake and conflict check", 0, 3, 0),
                ("Engagement letter", 3, 4, 0),
                ("Research and drafting", 7, 30, 1),
                ("Filing or submission", 37, 8, 1),
                ("Hearings and follow-up", 45, 40, 2),
                ("Closure report", 85, 5, 2),
            ],
        },
    },
    "Finance / Audit": {
        "roles": [PM_ROLE, "Partner", "Audit Manager", "Senior Auditor", "Article Assistant", "Tax Consultant", "Other"],
        "template": {
            "name": "Statutory Audit",
            "description": "Planning to signed report of a yearly audit",
            "duration_days": 45,
            "milestones": [("Audit Plan Agreed", 6), ("Fieldwork Done", 29), ("Report Signed", 44)],
            "tasks": [
                ("Engagement and audit plan", 0, 7, 0),
                ("Collect trial balance and records", 7, 5, 1),
                ("Vouching and verification", 12, 15, 1),
                ("Queries with client", 27, 8, 2),
                ("Draft and final report", 35, 10, 2),
            ],
        },
    },
    "Engineering / EPC": {
        "roles": [PM_ROLE, "Design Engineer", "Procurement Engineer", "Site Engineer", "Quality Inspector", "Safety Officer", "Commissioning Engineer", "Other"],
        "template": {
            "name": "EPC Project",
            "description": "Engineering, procurement, construction and commissioning",
            "duration_days": 240,
            "milestones": [("Design Frozen", 59), ("Equipment Delivered", 149), ("Commissioned", 239)],
            "tasks": [
                ("Basic and detailed engineering", 0, 60, 0),
                ("Vendor selection and purchase orders", 45, 45, 1),
                ("Equipment manufacturing and delivery", 90, 60, 1),
                ("Erection and installation", 150, 60, 2),
                ("Testing and commissioning", 210, 30, 2),
            ],
        },
    },
    "Media / Production": {
        "roles": [PM_ROLE, "Producer", "Director", "Script Writer", "Editor", "Camera Crew", "Sound Engineer", "Other"],
        "template": {
            "name": "Video Production",
            "description": "Script to delivery of a film or ad",
            "duration_days": 45,
            "milestones": [("Script Locked", 9), ("Shoot Wrapped", 24), ("Final Cut Delivered", 44)],
            "tasks": [
                ("Script and storyboard", 0, 10, 0),
                ("Casting and locations", 10, 7, 1),
                ("Shoot", 17, 8, 1),
                ("Editing and sound", 25, 14, 2),
                ("Client review and final cut", 39, 6, 2),
            ],
        },
    },
    "Government / NGO": {
        "roles": [PM_ROLE, "Programme Officer", "Field Coordinator", "Monitoring Officer", "Finance Officer", "Volunteer", "Other"],
        "template": {
            "name": "Community Programme",
            "description": "Baseline survey to impact report of a funded programme",
            "duration_days": 180,
            "milestones": [("Baseline Done", 29), ("Mid-Term Review", 89), ("Impact Report", 179)],
            "tasks": [
                ("Baseline survey", 0, 30, 0),
                ("Partner and beneficiary onboarding", 30, 20, 1),
                ("Field activities", 50, 100, 1),
                ("Monitoring visits", 60, 100, 2),
                ("Impact report to donor", 160, 20, 2),
            ],
        },
    },
    "General": {
        "roles": [PM_ROLE, "Team Lead", "Team Member", "Coordinator", "Consultant", "Other"],
        "template": {
            "name": "General Project",
            "description": "Plan, do and close any project",
            "duration_days": 30,
            "milestones": [("Plan Ready", 4), ("Work Done", 24), ("Project Closed", 29)],
            "tasks": [
                ("Plan the work", 0, 5, 0),
                ("Do the work", 5, 20, 1),
                ("Review and close", 25, 5, 2),
            ],
        },
    },
}


CUSTOM_BASE = "General"  # a company's own industry starts from these roles and this template


def preset(industry: str) -> dict:
    """The preset of an industry; a company's own industry (one not in the list) uses the General preset."""
    return INDUSTRIES.get(industry) or INDUSTRIES[CUSTOM_BASE]


def template_payload(industry: str) -> dict:
    """The starter template of an industry as a TemplateIn body."""
    t = preset(industry)["template"]
    return {
        "name": t["name"],
        "description": t["description"],
        "duration_days": t["duration_days"],
        "milestones": [{"name": name, "due_offset": due} for name, due in t["milestones"]],
        "tasks": [
            {"title": title, "start_offset": start, "duration_days": days, "milestone_index": ms}
            for title, start, days, ms in t["tasks"]
        ],
    }
