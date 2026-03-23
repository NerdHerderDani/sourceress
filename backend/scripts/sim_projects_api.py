import os
os.environ['DB_URL'] = 'sqlite:///./data/sim.db'

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db import engine
from app.projects import Project
from app.project_entity import ProjectEntity

client = TestClient(app)

# migrate DB to head
import subprocess, sys
subprocess.check_call([sys.executable, '-m', 'alembic', 'upgrade', 'head'])

# create sample project + entity
with Session(engine) as s:
    p = Project(name='TEST', notes='')
    s.add(p)
    s.commit()
    s.refresh(p)
    pe = ProjectEntity(project_id=p.id, source='stack', external_id='123', display_name='Stack Person', url='https://stackoverflow.com/users/123', summary_json={'avatar':''}, status='new', note='hi')
    s.add(pe)
    s.commit()
    pid = p.id

r = client.get(f'/projects/{pid}')
print('status', r.status_code)
print(r.json())
