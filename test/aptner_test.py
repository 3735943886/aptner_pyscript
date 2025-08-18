import aiohttp
import asyncio
from datetime import datetime, timedelta

APTNER_LOGIN = {}
APTNER_BASEURL = 'https://v2.aptner.com'
APTNER_HEADERS = { 'Content-Type': 'application/json' }
APTNER_AUTH_RUNNING = False
APTNER_AUTH_COND = asyncio.Condition()
APTNER_SESSION = None

@pyscript_compile
def aptner_session(**kwargs):
  global APTNER_SESSION
  if APTNER_SESSION is None or APTNER_SESSION.closed:
    APTNER_SESSION = aiohttp.ClientSession(**kwargs)
  return APTNER_SESSION

@time_trigger('shutdown')
def aptner_close_session():
  global APTNER_SESSION
  if APTNER_SESSION and not APTNER_SESSION.closed:
    try:
      APTNER_SESSION.close()
    finally:
      APTNER_SESSION = None

@pyscript_compile
async def aptner_auth():
  global APTNER_LOGIN, APTNER_HEADERS, APTNER_AUTH_RUNNING, APTNER_AUTH_COND
  async with APTNER_AUTH_COND:
    if APTNER_AUTH_RUNNING:
      try:
        await asyncio.wait_for(APTNER_AUTH_COND.wait(), timeout = 30)
      finally:
        return
    APTNER_AUTH_RUNNING = True
  try:
    if 'Authorization' in APTNER_HEADERS:
      del APTNER_HEADERS['Authorization']
    response = await aptner_request('POST', '/auth/token', data = APTNER_LOGIN)
    APTNER_HEADERS['Authorization'] = 'Bearer ' + response['accessToken']
  finally:
    async with APTNER_AUTH_COND:
      APTNER_AUTH_RUNNING = False
      APTNER_AUTH_COND.notify_all()

@pyscript_compile
async def aptner_request(method, url, data = None):
  global APTNER_HEADERS, APTNER_BASEURL
  kwargs = { 'headers': APTNER_HEADERS }
  if method in ('PUT', 'POST') and data is not None:
      kwargs['json'] = data
  session = aptner_session(base_url = APTNER_BASEURL)
  async with session.request(method, url, **kwargs) as response:
    if response.status != 401 or url == '/auth/token':
      response.raise_for_status()
      try:
        return await response.json()
      except:
        return
  await aptner_auth()
  async with session.request(method, url, **kwargs) as response:
    response.raise_for_status()
    try:
      return await response.json()
    except:
      return

@service(supports_response = 'only')
def aptner_init_test(id, password):
  """yaml
name: 아파트너 로그인
description: 최초 아파트너 로그인 필요
fields:
  id:
    description: 아파트너아이디
    example: aptner
    required: true
  password:
    description: 아파트너암호
    example: password
    required: true
"""
  global APTNER_LOGIN
  APTNER_LOGIN['id'] = id
  APTNER_LOGIN['password'] = password
  try:
    aptner_auth()
    if 'Authorization' in APTNER_HEADERS:
      return { 'result': 'success' }
  except Exception as e:
    return { 'error': '{}: {}'.format(type(e).__name__, str(e)) }
  return { 'result': 'unknown' }

@service(supports_response = 'only')
def aptner_findcar_test(carno = None):
  """yaml
name: 아파트너 입출차확인
description: 아파트너에서 차량의 입/출차를 확인합니다
fields:
  carno:
    description: 차량번호
    example: 123가1234
"""
  monthlyAccessHistory = aptner_request('GET', '/pc/monthly-access-history')
  return {'result': monthlyAccessHistory}
