"""EOS Cloud Views

vw_home
vw_login
vw_servers
vw_configure
vw_stop
vw_account

logout
forbidden_view

"""
from pyramid.view import view_config, forbidden_view_config
from pyramid.security import remember, forget
from pyramid.httpexceptions import HTTPFound, HTTPForbidden
from pyramid.renderers import render_to_response

import requests
from http import cookies
from datetime import datetime


##############################################################################
#                                                                            #
# Supporting Functions - load universal session variables et al.             #
#                                                                            #
##############################################################################

def api_get(request_string, request):
    """Run an API call and handle exceptions.
    """
    rs = request.registry.settings.get('db_endpoint_i') + '/' + request_string

    #Pass auth_tkt as a cookie rather than header, though it shouldn't matter.
    cookie = {'auth_tkt':request.session['auth_tkt']}
    r = requests.get(rs, cookies=cookie)
    if r.status_code == 200:
        return r.json()
    else:
        #FIXME - ensure return to login form on receipt of a 401
        raise ValueError(r.text)

def api_post(request_string, request):
    rs = request.registry.settings.get('db_endpoint_i') + '/' + request_string

    #Pass auth_tkt in cookie rather than header.
    cookie = {'auth_tkt':request.session['auth_tkt']}
    r = requests.post(rs, headers=cookie)
    if r.status_code == 200:
        return r.json()
    else:
        #FIXME - ensure return to login form on receipt of a 401
        raise ValueError

def user_credit(request):
    return api_get('user', request)['credits']

def server_list(request):
    """Loads all servers for the logged-in user.
    """
    # return api_get('http://localhost:6543/servers?actor_id=' + request.session['username'], request)
    return api_get('servers', request)

def server_data(server_name, request):
    """Loads details of a specific server.
    """
    return api_get('servers/' + server_name, request)

def server_touches(server_name, request):
    """Loads log entries for a given server.
    """
    return api_get('servers/' + server_name + '/touches', request)

##############################################################################
#                                                                            #
# Pages Views - Actual pages on the portal                                   #
#                                                                            #
##############################################################################

#FIXME - home page should be login page.  This should be the /about page or summat.
@view_config(route_name='home', renderer='templates/home.pt')
def vw_home(request):
    """Main landing page for the portal. Contains reference information.
    """
    account = None
    try:
        account = api_get('user', request)
    except:
        #We need to be able to look at this page even if not logged in.
        account = dict()
    return dict(values      = [],
                logged_in   = account.get('username'),
                credit      = account.get('credits'))

@view_config(route_name='servers', renderer='templates/servers.pt')
def vw_servers(request):
    """Server View - Lists all servers available to the logged-in user.
    """
    account = None
    try:
        account = api_get('user', request)
    except:
        return logout(request)
    #Tell the browser how to query the database via the external endpoint.
    db_endpoint = request.registry.settings.get('db_endpoint_x')
    return dict(   logged_in   = account['username'],
                   user        = account['username'],
                   values      = server_list(request),
                   credit      = account['credits'],
                   token       = request.session['auth_tkt'],
                   db_endpoint = db_endpoint)

@view_config(route_name='configure', renderer='templates/configure.pt')
def vw_configure(request):
    """Config View - List details of a specific server.
    """
    #FIXME - this boilerplate could be made into a handle_logout decorator,
    #as well as adding token, db_endpoint, logged_in, credit to all templates.
    account = None
    try:
        account = api_get('user', request)
    except:
        return logout(request)
    server_name = request.matchdict['name']
    db_endpoint = request.registry.settings.get('db_endpoint_x')

    boost_levels = api_get('boostlevels', request)

    #Currently we get a 500 error if the server name is invalid.
    #This seems reasonable.

    return dict(   logged_in    = account['username'],
                   values       = server_list(request),
                   server       = server_data(server_name, request),
                   touches      = server_touches(server_name, request),
                   credit       = account['credits'],
                   boost_levels = boost_levels,
                   token        = request.session['auth_tkt'],
                   db_endpoint  = db_endpoint)

@view_config(route_name='account', renderer='templates/account.pt')
def vw_account(request):
    account = None
    try:
        account = api_get('user', request)
    except:
        return logout(request)
    return dict( logged_in = account['username'],
                 values    = server_list(request),
                 account   = account_details(request),
                 credit    = user_credit(request),
                 token     = request.session['auth_tkt'])

##############################################################################
#                                                                            #
# Login and logout methods with redirects                                    #
#                                                                            #
##############################################################################

@view_config(route_name='login', renderer='templates/login.pt')
def login(request):
    """Either log the user in or show the login page.
    """
    username = request.POST.get('username')
    account = None
    error_msg = None

    #1) If the user submitted the form, try to log in.
    if 'submit' in request.POST:
        user_url = request.registry.settings.get('db_endpoint_i') + '/user'
        r = requests.get(user_url, auth=(request.POST['username'], request.POST['password']))
        if r.status_code == 200:
            headers = remember(request, r.json()['username'])
            #FIXME - there should really be a regression test for this.
            request.session['auth_tkt'] = cookies.SimpleCookie(r.headers['Set-Cookie'])['auth_tkt'].value
            print ("Session token from DB: " + request.session['auth_tkt'])
            return HTTPFound(location=request.registry.settings.get('portal_endpoint') + '/servers', headers=headers)
        if r.status_code == 401:
            error_msg = "Username or password not recognised"
        else:
            error_msg = "Server error"
    #2) Already logged in, maybe?  See if any of the following raise an exception...
    else:
        try:
            auth_tkt = request.session['auth_tkt']
            #If that didn't raise an exception, try using it...
            error_msg = "Session has expired"
            account = api_get('user', request)
            username = account['username']
            print("Already logged in")
            headers = remember(request, username)
            return HTTPFound(location=request.registry.settings.get('portal_endpoint') + '/servers', headers=headers)
        except:
            pass #Continue to show login form.

    #FIXME - make use of error_msg and username if set.
    return dict(project='eos_portal', values=[], logged_in=None)

@view_config(route_name='logout')
def logout(request):
    """Forget the login credentials and redirect to the front page.
       Note that other methods rely on this to always return an HTTPFound instance.
    """
    headers = forget(request)
    if 'auth_tkt' in request.session:
        request.session.pop('auth_tkt')
    return HTTPFound(location=request.registry.settings.get('portal_endpoint'), headers=headers)

@view_config(route_name='test_configure', renderer='templates/configure.pt')
def test_configure(request):
    """Provides dummy values to the configure page so I can test it out without
       starting the eos-db server.
    """
    ram = 40
    cores = 1
    boosted = "Unboosted"
    boostremaining = "N/A"
    deboost_credit = 0
    deboost_time = 0
    if request.params.get('boost'):
        ram = 100
        cores = 8
        boosted = "Boosted"
        boostremaining = "10 hrs, 12 min"
        deboost_credit = 30
        deboost_time = int(datetime.now().strftime("%s")) + ((10 * 60) + 12) * 60;

    #Boost levels copied from the eos_db defaults in settings.example.py
    bl_baseline = dict( label='Standard', ram=16, cores=1 )

    bl_levels = ( dict( label='Standard+', ram=40,  cores=2,  cost=1  ),
                  dict( label='Large',     ram=100, cores=8,  cost=3  ),
                  dict( label='Max',       ram=400, cores=16, cost=12 ))

    return dict(   logged_in    = 'nobody',
                   values       = [ { "artifact_name": "dummy" } ],
                   server       = dict(
                       artifact_name = "dummy",
                       artifact_uuid = "dummy-123",
                       state         = "Started",
                       boostremaining= boostremaining,
                       change_dt     = "2015-05-20 17:32",
                       ram           = ram,
                       cores         = cores,
                       create_dt     = "2015-05-18 18:38",
                       boosted       = boosted,
                       artifact_id   = 123,
                       deboost_time  = deboost_time,
                       deboost_credit= deboost_credit,
                                  ),
                   touches      = [],
                   credit       = 500,
                   token        = 'none',
                   boost_levels = dict(baseline=bl_baseline, levels=bl_levels, capacity=()),
                   db_endpoint  = 'none://')
