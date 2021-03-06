from flask import redirect, url_for, flash, render_template, \
				Response, current_app, request, send_from_directory, abort

from flask_login import current_user, login_required
from app.main import bp
from app.util import hostinfo, isAcceptableTarget
from app.auth.wrappers import isAuthenticated
from app.admin.forms import DeleteForm
from app.main.forms import RescanForm
from app.models import RescanTask
from app import db
import json
from datetime import datetime

@bp.route('/')
@isAuthenticated
def index():
	return redirect(url_for('main.search'))

# Serve media files in case the front-end proxy doesn't do it
@bp.route('/media/<path:filename>')
def send_media(filename):
	# If you're looking at this function, wondering why your files aren't sending...
	# It's probably because current_app.config['MEDIA_DIRECTORY'] isn't pointing to an absolute file path
	return send_from_directory(current_app.config['MEDIA_DIRECTORY'], filename)

@bp.route('/search')
@isAuthenticated
def search():
	query = request.args.get('query', '')
	page = int(request.args.get('page', 1))
	format = request.args.get('format', '')
	scan_ids = request.args.get('includeScanIDs', '')
	includeHistory = request.args.get('includeHistory', False)

	results_per_page = current_user.results_per_page
	if includeHistory:
		searchIndex = "nmap_history"
	else:
		searchIndex = "nmap"

	searchOffset = results_per_page * (page-1)
	count, context = current_app.elastic.search(query, results_per_page, searchOffset, searchIndex=searchIndex)
	totalHosts = current_app.elastic.totalHosts()

	if includeHistory:
		next_url = url_for('main.search', query=query, page=page+1, includeHistory=includeHistory) \
			 if count > page * results_per_page else None
		prev_url = url_for('main.search', query=query, page=page - 1, includeHistory=includeHistory) \
			if page > 1 else None
	else:
		next_url = url_for('main.search', query=query, page=page+1) \
			 if count > page * results_per_page else None
		prev_url = url_for('main.search', query=query, page=page - 1) \
			if page > 1 else None

	# what kind of output are we looking for?
	if format == 'hostlist':
		hostlist = []
		for host in context:
			if scan_ids:
				hostlist.append(str(host['ip']) + ',' + str(host['scan_id']))
			else:
				hostlist.append(str(host['ip']))
		return Response('\n'.join(hostlist), mimetype='text/plain')
	else:
		return render_template("search.html", query=query, numresults=count, totalHosts=totalHosts, page=page, hosts=context, next_url=next_url, prev_url=prev_url)

@bp.route('/searchmodal')
@isAuthenticated
def search_modal():
	return render_template("includes/search_modal_content.html")

def determine_data_version(hostdata):
	if 'agent_version' in hostdata:
		# Do math on version here to determine if we need to fall "up" to 0.6.4
		version = hostdata['agent_version']
		verlist = version.split('.')
		for idx,item in enumerate(verlist):
			verlist[idx] = int(item)

		if verlist[1] < 6 or (verlist[1] == 6 and verlist[2] < 4):
			version = '0.6.4'
	else:
		# Fall "up" to 0.6.4 which is the last release before we introduced versioned host templates
		version = '0.6.4'

	return version

@bp.route('/host/<ip>')
@bp.route('/host/<ip>/')
@isAuthenticated
def host(ip):
	info, context = hostinfo(ip)
	delForm = DeleteForm()
	delHostForm = DeleteForm()
	rescanForm = RescanForm()

	version = determine_data_version(context)

	return render_template("host/versions/"+version+"/summary.html", **context, host=context, info=info, delForm=delForm, delHostForm=delHostForm, \
		rescanForm=rescanForm)


@bp.route('/host/<ip>/history')
@bp.route('/host/<ip>/history/')
@isAuthenticated
def host_history(ip):
	info, context = hostinfo(ip)
	page = int(request.args.get('p', 1))
	searchOffset = current_user.results_per_page * (page-1)

	delHostForm = DeleteForm()
	rescanForm = RescanForm()

	count, context = current_app.elastic.gethost_history(
		ip, current_user.results_per_page, searchOffset)
	if count == 0:
		abort(404)
	next_url = url_for('main.host_history', ip=ip, p=page + 1) \
		if count > page * current_user.results_per_page else None
	prev_url = url_for('main.host_history', ip=ip, p=page - 1) \
		if page > 1 else None

	return render_template("host/versions/0.6.5/history.html", ip=ip, info=info, page=page, numresults=count, hosts=context, next_url=next_url, prev_url=prev_url, \
		delHostForm=delHostForm, rescanForm=rescanForm)

@bp.route('/host/<ip>/<scan_id>')
@isAuthenticated
def host_historical_result(ip, scan_id):
	delForm = DeleteForm()
	delHostForm = DeleteForm()
	rescanForm = RescanForm()
	info, context = hostinfo(ip)
	count, context = current_app.elastic.gethost_scan_id(scan_id)

	version = determine_data_version(context)

	return render_template("host/versions/"+version+"/summary.html", host=context, info=info, **context, delForm=delForm, delHostForm=delHostForm, rescanForm=rescanForm)

@bp.route('/host/<ip>/<scan_id>.<ext>')
@isAuthenticated
def export_scan(ip, scan_id, ext):
	if ext not in ['xml', 'nmap', 'gnmap', 'json']:
		abort(404)

	export_field = f"{ext}_data"

	if ext == 'json':
		mime = "application/json"
	else:
		mime = "text/plain"

	count, context = current_app.elastic.gethost_scan_id(scan_id)
	if ext == 'json' and count > 0:
		return Response(json.dumps(context), mimetype=mime)
	elif count > 0 and export_field in context:
		return Response(context[export_field], mimetype=mime)
	else:
		abort(404)

@bp.route('/host/<ip>/screenshots')
@bp.route('/host/<ip>/screenshots/')
@isAuthenticated
def host_screenshots(ip):
	page = int(request.args.get('p', 1))
	searchOffset = current_user.results_per_page * (page-1)

	delHostForm = DeleteForm()
	rescanForm = RescanForm()
	info, context = hostinfo(ip)
	total_entries, screenshots = current_app.elastic.get_host_screenshots(ip, current_user.results_per_page, searchOffset)

	next_url = url_for('main.host_screenshots', ip=ip, p=page + 1) \
		if total_entries > page * current_user.results_per_page else None
	prev_url = url_for('main.host_screenshots', ip=ip, p=page - 1) \
		if page > 1 else None

	version = determine_data_version(context)

	return render_template("host/versions/"+version+"/screenshots.html", **context, historical_screenshots=screenshots, numresults=total_entries, \
		info=info, delHostForm=delHostForm, rescanForm=rescanForm, next_url=next_url, prev_url=prev_url)

@bp.route('/host/<ip>/rescan', methods=['POST'])
# login_required ensures that an actual user is logged in to make the request
# opposed to isAuthenticated checking site config to see if login is required first
@login_required
def rescan_host(ip):
	rescanForm = RescanForm()

	if rescanForm.validate_on_submit():
		if not isAcceptableTarget(ip):
			# Someone is requesting we scan an ip that isn't allowed
			flash("We're not allowed to scan %s" % ip, "danger")
			return redirect(request.referrer)

		incompleteScans = current_app.ScopeManager.getIncompleteScans()

		for scan in incompleteScans:
			if ip == scan.target:
				if scan.dispatched == True:
					status = "dispatched"
					if (datetime.utcnow() - scan.date_dispatched).seconds > 1200:
						# 20 minutes have past since dispatch, something probably wen't seriously wrong
						# move it back to not dispatched and update the cached rescan data
						scan.dispatched = False
						db.session.add(scan)
						db.session.commit()
						current_app.ScopeManager.updatePendingRescans()
						current_app.ScopeManager.updateDispatchedRescans()
						flash("Refreshed existing rescan request for %s" % ip, "success")
						return redirect(request.referrer)
				else:
					status = "pending"
				flash("There's already a %s rescan request for %s" % (status, ip), "warning")
				return redirect(request.referrer)

		rescan = RescanTask(user_id=current_user.id, target=ip)
		db.session.add(rescan)
		db.session.commit()
		flash("Requested rescan of %s" % ip, "success")
		current_app.ScopeManager.updatePendingRescans()
		current_app.ScopeManager.updateDispatchedRescans()
		return redirect(request.referrer)

@bp.route("/random")
@bp.route("/random/")
def randomHost():
	randomHost = current_app.elastic.random_host()
	if not randomHost:
		abort(404)
	ip = randomHost['hits']['hits'][0]['_source']['ip']
	info, context = hostinfo(ip)
	delForm = DeleteForm()
	delHostForm = DeleteForm()
	rescanForm = RescanForm()

	version = determine_data_version(context)

	return render_template("host/versions/"+version+"/summary.html", **context, host=context, info=info, delForm=delForm, delHostForm=delHostForm, \
		rescanForm=rescanForm)


@bp.route("/screenshots")
@bp.route("/screenshots/")
def browseScreenshots():
	page = int(request.args.get('p', 1))
	searchOffset = current_user.results_per_page * (page-1)

	total_hosts, total_screenshots, hosts = current_app.elastic.get_current_screenshots(current_user.results_per_page, searchOffset)

	next_url = url_for('main.browseScreenshots', p=page + 1) \
		if total_hosts > page * current_user.results_per_page else None
	prev_url = url_for('main.browseScreenshots', p=page - 1) \
		if page > 1 else None

	return render_template("screenshots.html", numresults=total_screenshots, hosts=hosts, next_url=next_url, prev_url=prev_url)