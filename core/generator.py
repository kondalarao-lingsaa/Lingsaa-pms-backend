import random

class Generator:
    def client_username_generator():
        id = 'L'
        while len(id)<6:
            id+=str(random.randint(0,9))
        return id
    
    def users_username_generator():
        id = 'L'
        while len(id)<6:
            id+=str(random.randint(0,9))
        return id

    def project_number():
        return f"PRJ-{random.randint(0, 9999):04d}"    # will generate the project number 

    def task_number():
        return f"TSK-{random.randint(0, 9999):04d}"    # will generate the task number 


