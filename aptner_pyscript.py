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
def aptner_init(id, password):
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
def aptner_findcar(carno = None):
  """yaml
name: 아파트너 입출차확인
description: 아파트너에서 차량의 입/출차를 확인합니다
fields:
  carno:
    description: 차량번호
    example: 123가1234
"""
  monthlyAccessHistory = aptner_request('GET', '/pc/monthly-access-history')
  response = {}
  for monthlyParkingHistory in monthlyAccessHistory['monthlyParkingHistoryList']:
    for visitCarUseHistoryReport in monthlyParkingHistory['visitCarUseHistoryReportList']:
      if carno == None or visitCarUseHistoryReport['carNo'] == carno:
        if visitCarUseHistoryReport['carNo'] not in response:
          response[visitCarUseHistoryReport['carNo']] = {
            'status': 'out' if visitCarUseHistoryReport['isExit'] else 'in',
          }
          if 'inDatetime' in visitCarUseHistoryReport and visitCarUseHistoryReport['inDatetime'] is not None:
            response[visitCarUseHistoryReport['carNo']]['intime'] = visitCarUseHistoryReport['inDatetime']
          if 'outDatetime' in visitCarUseHistoryReport and visitCarUseHistoryReport['outDatetime'] is not None:
            response[visitCarUseHistoryReport['carNo']]['outtime'] = visitCarUseHistoryReport['outDatetime']
        if visitCarUseHistoryReport['carNo'] == carno:
          break
  return response

@service(supports_response = 'only')
def aptner_fee():
  """yaml
name: 아파트너 관리비
description: 아파트너에서 최근 관리비를 확인합니다
"""
  fee = aptner_request('GET', '/fee/detail')['fee']
  return { 'year': fee['year'], 'month': fee['month'], 'fee': fee['currentFee'], 'details': { item["name"]: item["value"] for item in fee['details'] }}

@service(supports_response = 'only')
def aptner_get_reserve_status():
  """yaml
name: 아파트너 방문차량 예약현황
description: 아파트너에서 방문차량의 주차 예약현황을 확인합니다
"""
  totalpages = 0
  currentpage = 0
  today = datetime.today().date()
  result = {}
  while True:
    currentpage = currentpage + 1
    reservedcars = aptner_request('GET', '/pc/reserves?pg={}'.format(currentpage))
    if totalpages == 0:
      totalpages = reservedcars['totalPages']
    for reservedcar in reservedcars['reserveList']:
      visitdate = datetime.strptime(reservedcar['visitDate'], "%Y.%m.%d").date()
      if today < visitdate:
        if reservedcar['carNo'] not in result:
          result[reservedcar['carNo']] = []
        result[reservedcar['carNo']].append(visitdate)
    if currentpage >= totalpages:
      break
  for car in result:
    result[car].sort()
    ranges = []
    start_of_range = result[car][0]
    for i in range(1, len(result[car])):
      previous_date = result[car][i-1]
      current_date = result[car][i]
      if (current_date - previous_date) > timedelta(days = 1):
        ranges.append({ 'from': start_of_range, 'to': previous_date })
        start_of_range = current_date
    ranges.append({ 'from': start_of_range, 'to': result[car][-1] })
    result[car] = ranges
  return result

@service()
def aptner_reserve_car(date, purpose, carno, days, phone):
  """yaml
name: 아파트너 방문차량 예약
description: 아파트너에서 방문차량의 주차를 예약합니다
fields:
  date:
    description: 방문일시
    example: 2025.01.01
    required: true
  purpose:
    description: 방문목적
    example: 기타
    required: true
  carno:
    description: 차량번호
    example: 111가1111
    required: true
  days:
    description: 방문기간
    example: 1
    required: true
  phone:
    description: 연락처
    example: 010-0000-0000
    required: true
"""
  try:
    aptner_request('POST', '/pc/reserve/', { 'visitDate': date, 'purpose': purpose, 'carNo': carno, 'days': days, 'phone': phone })
  except:
    pass
