#!/usr/bin/env python

from flask import request
from functools import wraps
from werkzeug.wsgi import DispatcherMiddleware
from werkzeug.serving import run_simple
import flask
import os
import mimetypes
import urllib2
import restfulgit
import repos_service
import jobs_service
from restfulgit import app_factory as restfulgit_app_factory


class RestfulGitConfig(object):
  RESTFULGIT_REPO_BASE_PATH = repos_service.get_workspace_root()

app = flask.Flask(__name__)
full_app = DispatcherMiddleware(
  app,
  {
    '/restfulgit': restfulgit_app_factory.create_app(RestfulGitConfig),
  },
)


def get_buildbot_password_or_die():
  """Fetches the buildbot password either from GCP metadata or from an environment variable."""
  try:
    url = 'http://metadata.google.internal/computeMetadata/v1/instance/attributes/buildbot-password'
    headers = {'Metadata-Flavor': 'Google'}
    request = urllib2.Request(url, headers=headers)
    response = urllib2.urlopen(request)
    return response.read()
  except (urllib2.URLError, urllib2.HTTPError):
    # Fall through to the environment variable.
    return os.environ['BUILDBOT_PASSWORD']


def check_auth(username, password):
  return username == 'admin' and password == get_buildbot_password_or_die()


def unauthorized():
  return flask.Response('Unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})


def auth_required(f):
  @wraps(f)
  def decorated(*args, **kwargs):
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
      return unauthorized()
    return f(*args, **kwargs)
  return decorated


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
@auth_required
def catch_all(path):
  return '404', 404


@app.route('/')
@auth_required
def index():
  jobs = jobs_service.list_jobs()
  builds = jobs_service.list_builds(limit=20)
  return flask.render_template('index.html', builds=builds, jobs=jobs)


@app.route('/builds')
@auth_required
def builds():
  builds = jobs_service.list_builds()
  return flask.render_template('builds.html', builds=builds)


@app.route('/jobs')
@auth_required
def jobs():
  jobs = jobs_service.list_jobs()
  return flask.render_template('jobs.html', jobs=jobs)


@app.route('/job/<int:job_id>/browse')
@auth_required
def job_browse(job_id):
  job = jobs_service.get_job(job_id)
  return flask.render_template('browse.html', job=job)


@app.route('/job/<int:job_id>/browse/<path:ref>')
@auth_required
def job_browse_ref(job_id, ref):
  job = jobs_service.get_job(job_id)
  return flask.render_template('browse_ref.html', job=job, ref=ref)


@app.route('/builds/<int:build_id>')
@auth_required
def build(build_id):
  build = jobs_service.get_build(build_id)
  return flask.render_template('build.html', build=build)


@app.route('/api/jobs/<int:job_id>/contents/<path:path>')
@auth_required
def contents(path):
  ref = request.args.get('ref')
  assert ref
  data = request.get_json()
  repo = repos_service.init_repo(
      url=data['url'],
      branch=data['branch'])
  content = repos_service.download(
      repo=repo,
      branch=data['branch'],
      path=data['path'])
  resp = app.make_response(content)
  mimetype = mimetypes.guess_type(data['path'])[0]
  if mimetype:
    resp.mimetype = mimetype
  return resp


# @app.route('/api/contents/download', methods=['POST'])
# @auth_required
# def download_contents():
#   data = request.get_json()
#   repo = repos_service.init_repo(
#       url=data['url'],
#       branch=data['branch'])
#   content = repos_service.download(
#       repo=repo,
#       branch=data['branch'],
#       path=data['path'])
#   resp = app.make_response(content)
#   mimetype = mimetypes.guess_type(data['path'])[0]
#   if mimetype:
#     resp.mimetype = mimetype
#   return resp


# @app.route('/api/contents/update', methods=['POST'])
# @auth_required
# def update_contents():
#   data = request.get_json()
#   repo = repos_service.init_repo(
#       url=data['url'],
#       branch=data['branch'])
#   resp = repos_service.update(
#       repo=repo,
#       branch=data['branch'],
#       path=data['path'],
#       content=data['content'],
#       sha=data['sha'],
#       message=data['message'],
#       committer=data['committer'],
#       author=data['author'])
#   return flask.jsonify({'success': True, 'resp': resp})


@app.route('/api/jobs', methods=['POST'])
@auth_required
def create_job():
  # TODO: better JSON API parsing and error responses.
  data = request.get_json()
  assert data.get('git_url')
  assert data.get('remote')
  assert data.get('env')
  assert data['env'].get('WEBREVIEW_API_KEY')

  job_id = jobs_service.create_job(
      git_url=data['git_url'],
      remote=data['remote'],
      env=data['env'],
  )
  return flask.jsonify({'success': True, 'job_id': job_id})


@app.route('/api/jobs/sync', methods=['GET', 'POST'])
@auth_required
def sync_jobs():
  data = jobs_service.sync_all_jobs()
  jobs_with_new_builds = [job_id for job_id in data if data[job_id]]
  if jobs_with_new_builds:
    message = 'Refs changed, enqueued builds from %s jobs.' % len(jobs_with_new_builds)
  else:
    message = 'No refs changed in any jobs, nothing to build.'
  return flask.jsonify({'success': True, 'message': message})



@app.route('/api/jobs/<int:job_id>/sync', methods=['GET', 'POST'])
@auth_required
def sync_job(job_id):
  # Update refs and trigger all builds.
  build_ids = jobs_service.sync_job(job_id)
  if build_ids:
    message = 'Refs changed, enqueued %s builds.' % len(build_ids)
  else:
    message = 'No refs changed, nothing to build.'
  return flask.jsonify({'success': True, 'message': message})


@app.route('/api/jobs/<int:job_id>/run', methods=['GET', 'POST'])
@auth_required
def run_job(job_id):
  ref = request.args.get('ref')
  commit_sha = request.args.get('commit_sha')
  assert ref
  assert commit_sha
  # Trigger build of single ref and commit SHA.
  build_id = jobs_service.enqueue_build(job_id, ref, commit_sha)
  return flask.jsonify({'success': True, 'build_id': build_id, 'message': 'Build enqueued.'})


if __name__ == '__main__':
  run_simple('localhost', 5000, full_app, use_reloader=True, use_debugger=True)
