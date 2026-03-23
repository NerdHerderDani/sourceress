import os, sys, subprocess
from pathlib import Path

# Use isolated sqlite DB
os.environ['DB_URL'] = 'sqlite:///./data/smoke.db'

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent

# Run migrations
subprocess.check_call([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=str(BACKEND))

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db import engine
from app.projects import Project
from app.project_entity import ProjectEntity
from app.models import Candidate

client = TestClient(app)

def get_ok(path: str):
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code, r.text[:200])
    return r

# Basic pages
get_ok('/')
get_ok('/projects-ui')
get_ok('/stack')
get_ok('/openalex')
get_ok('/linkedin')

# Create a project
r = client.post('/projects', data={'name': 'TEST'})
assert r.status_code == 200
pid = r.json()['item']['id']

# Create a fake github candidate row to allow enrichment
with Session(engine) as s:
    s.add(Candidate(login='octocat', html_url='https://github.com/octocat', avatar_url='', name='Octo', company='', location='', bio='', followers=1, email='', email_source='none', profile_json={}))
    s.commit()

# Add github entity (legacy path)
r = client.post(f'/projects/{pid}/add', data={'login': 'octocat', 'note': 'hi', 'status': 'new'})
assert r.status_code == 200, r.text

# Add stack entity
r = client.post(f'/projects/{pid}/add', data={'source': 'stack', 'external_id': '123', 'display_name': 'Stack Person', 'url': 'https://stackoverflow.com/users/123', 'status': 'new'})
assert r.status_code == 200, r.text

# Fetch project detail
r = get_ok(f'/projects/{pid}')
data = r.json()
assert data['ok'] is True
assert len(data['items']) >= 2

# Update status for stack entity
r = client.post(f'/projects/{pid}/status', data={'source': 'stack', 'external_id': '123', 'status': 'contacted'})
assert r.status_code == 200

# Remove stack entity
r = client.post(f'/projects/{pid}/remove', data={'source': 'stack', 'external_id': '123'})
assert r.status_code == 200

# LinkedIn URL save
r = client.post('/candidates/octocat/linkedin-url', data={'linkedin_url': 'https://www.linkedin.com/in/example/'})
assert r.status_code == 200, r.text

print('SMOKE_OK')
