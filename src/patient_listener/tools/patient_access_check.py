"""Local HTTP enrollment/revocation check. Creates and revokes only a fresh test device."""
import argparse
import getpass
from http.cookiejar import CookieJar
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPCookieProcessor
from .generate_plan import NoRedirect


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--person',default='margaret')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args(argv)
    if not 1 <= args.port <= 65535:parser.error('port must be 1..65535')
    base=f'http://127.0.0.1:{args.port}'
    person=quote(args.person,safe='')
    device=secrets.token_hex(24)
    opener=build_opener(NoRedirect,HTTPCookieProcessor(CookieJar()))
    authorization_id=None
    helper=None
    stage="initial authorization check"
    status=None

    def call(path,method='GET',body=None,console=False):
        headers={'X-PL-Device':device,'Content-Type':'application/json'}
        if console:headers['Authorization']='Bearer '+helper
        request=Request(base+path,method=method,headers=headers,
                        data=json.dumps(body).encode() if body is not None else None)
        try:
            with opener.open(request,timeout=15) as response:
                return response.status,json.load(response)
        except HTTPError as exc:
            return exc.code,None  # Do not print response bodies containing credentials.

    try:
        status,_=call('/api/session?person='+person)
        if status != 401:
            print('Expected unauthenticated HTTP 401. Enable PATIENT_ENROLLMENT_REQUIRED=true and restart the server first. No device was created.')
            return 1
        print('PASS: an unlinked device cannot obtain a session token.')
        helper=getpass.getpass('Linked therapist/carer console token (not the Nebius key): ').strip()
        if not helper or len(helper)>256 or any(ord(c)<32 or ord(c)==127 for c in helper):
            parser.error('Enter a valid console token')
        stage='helper authentication'; status=None
        status,identity=call('/api/console/me',console=True)
        if status!=200 or not isinstance(identity,dict) or identity.get('role') not in {'therapist','carer'}:
            raise ValueError('helper authentication')
        print('PASS: the running server recognizes the helper console token.')
        stage='setup code creation'; status=None
        status,invite=call('/api/console/patients/'+person+'/device-links','POST',console=True)
        if status!=200:raise ValueError('helper authorization or setup creation')
        stage='device enrollment'; status=None
        status,linked=call('/api/patient/enroll','POST',{'setup_code':invite['setup_code']})
        if status!=200:raise ValueError('device enrollment')
        authorization_id=linked['authorization_id']
        stage='authorized session issuance'; status=None
        status,session=call('/api/session?person='+person)
        if status!=200 or not isinstance(session,dict) or not session.get('token'):raise ValueError('authorized session issuance')
        print('PASS: the single-use setup code enrolled the test device and allowed a session token.')
        stage='single-use code enforcement'; status=None
        status,_=call('/api/patient/enroll','POST',{'setup_code':invite['setup_code']})
        if status!=400:raise ValueError('single-use enforcement')
        print('PASS: the setup code cannot be reused.')
        stage='test-device revocation'; status=None
        status,result=call('/api/console/patients/'+person+'/devices/'+authorization_id,'DELETE',console=True)
        if status!=200 or not isinstance(result,dict) or not result.get('revoked'):raise ValueError('device revocation')
        authorization_id=None
        stage='revoked credential rejection'; status=None
        status,_=call('/api/session?person='+person)
        if status!=401:raise ValueError('revoked credential rejection')
        print('PASS: revocation blocked further session tokens. Test device removed; no practice or model call was started.')
        return 0
    except KeyboardInterrupt:
        print('\nCheck cancelled.')
        return 130
    except (URLError,ValueError,KeyError,TypeError,OSError):
        suffix=f' (HTTP {status})' if status is not None else ''
        print('Check failed at '+stage+suffix+'. No secrets were printed.')
        if stage=='helper authentication' and status==401:
            print('The running server rejected this console token. It may be incorrect/expired, or issued from a different database. Make sure the server and token tool use the same existing database file.')
        elif status==404:
            print('Check the selected person, helper link, server port and copied API files.')
        elif status==403:
            print('Use a real linked therapist/carer credential, not judge-demo or agent credentials.')
        elif stage=='authorized session issuance' and status==401:
            print('Enrollment completed but the device cookie was not accepted. Check HTTPS/cookie settings and use one consistent server origin.')
        elif status==400:
            print('Check HTTPS requirements and whether the setup code is expired or already used.')
        else:
            print('Check server reachability/configuration and its sanitized logs for this stage.')
        return 1
    finally:
        if authorization_id is not None and helper:
            try:
                status,_=call('/api/console/patients/'+person+'/devices/'+authorization_id,'DELETE',console=True)
                if status!=200:print('Test-device cleanup could not be confirmed; review linked devices in the helper API.')
            except Exception:
                print('Test-device cleanup could not be confirmed; review linked devices in the helper API.')


if __name__=='__main__':
    raise SystemExit(main())
