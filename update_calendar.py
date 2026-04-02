import os
import requests
import pytz
from datetime import datetime, timedelta
from icalendar import Calendar, Event

# --- [설정] ---
NX, NY = 60, 127             # 서울 격자
REG_ID = '11B10101'          # 중기육상(서울)
REG_TEMP_ID = '11B10101'     # 중기기온(서울)
API_KEY = os.environ.get('KMA_API_KEY')

def get_emoji(sky, pty=None, wf=None):
    """단기/중기 통합 이모지 변환"""
    if wf: # 중기예보 텍스트 기반
        if '비' in wf: return "🌧️"
        if '눈' in wf: return "🌨️"
        if '구름많음' in wf: return "⛅"
        if '흐림' in wf: return "☁️"
        if '맑음' in wf: return "☀️"
    if pty and pty != '0': # 단기예보 코드 기반
        if pty in ['1', '4']: return "🌧️"
        if pty == '2': return "🌨️"
        if pty == '3': return "❄️"
    if sky == '1': return "☀️"
    if sky == '3': return "⛅"
    if sky == '4': return "☁️"
    return "🌡️"

def fetch_data(url):
    try:
        res = requests.get(url)
        return res.text if res.status_code == 200 else None
    except: return None

def main():
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.now(seoul_tz)
    cal = Calendar()
    cal.add('X-WR-CALNAME', '기상청 날씨 달력')

    # 1. 단기 예보 (0~3일) 수집
    base_date = now.strftime('%Y%m%d')
    url_short = f"https://apihub.kma.go.kr/api/typ01/url/vsc_sfc_af_dtl.php?base_date={base_date}&nx={NX}&ny={NY}&authKey={API_KEY}"
    raw_short = fetch_data(url_short)
    
    daily_short = {}
    if raw_short:
        for line in raw_short.split('\n'):
            if line.startswith('#') or len(line.split()) < 15: continue
            cols = line.split()
            dt, tmp, sky, pty, pop = cols[0], cols[12], cols[13], cols[14], cols[15]
            if dt not in daily_short: daily_short[dt] = {'tmps': [], 'details': []}
            daily_short[dt]['tmps'].append(float(tmp))
            daily_short[dt]['details'].append(f"[{cols[1][:2]}:00] {get_emoji(sky, pty)} {tmp}°C, ☔{pop}%")

    # 2. 중기 예보 (4~10일) 수집 및 파싱
    # 발표시간 기준: 오전 6시(0600) 혹은 오후 6시(1800)
    tm_fc = now.strftime('%Y%m%d') + ("0600" if now.hour < 18 else "1800")
    url_mid_land = f"https://apihub.kma.go.kr/api/typ01/url/mid_sfc_af_dtl.php?reg_id={REG_ID}&tm_fc={tm_fc}&authKey={API_KEY}"
    url_mid_temp = f"https://apihub.kma.go.kr/api/typ01/url/mid_temp_af_dtl.php?reg_id={REG_TEMP_ID}&tm_fc={tm_fc}&authKey={API_KEY}"
    
    raw_land = fetch_data(url_mid_land)
    raw_temp = fetch_data(url_mid_temp)

    mid_forecast = {}
    if raw_land and raw_temp:
        l_cols = [l for l in raw_land.split('\n') if not l.startswith('#') and len(l) > 10][0].split()
        t_cols = [l for l in raw_temp.split('\n') if not l.startswith('#') and len(l) > 10][0].split()
        
        for i in range(3, 11): # 3일후~10일후 데이터 추출 (기상청 인덱스 기준)
            target_dt = (now + timedelta(days=i)).strftime('%Y%m%d')
            # 기상청 중기예보 컬럼 순서에 맞춰 wf(날씨), ta(기온) 추출 (API별 상이)
            # 여기서는 i일 후의 날씨와 기온 정보를 매칭합니다.
            mid_forecast[target_dt] = {
                'wf': l_cols[i+1] if i <= 7 else l_cols[i+5], # 예시 인덱스
                'tmin': t_cols[i*2], 'tmax': t_cols[i*2+1]
            }

    # 3. 캘린더 생성 (0~10일 통합)
    for i in range(11):
        target_dt_obj = now + timedelta(days=i)
        target_dt_str = target_dt_obj.strftime('%Y%m%d')
        event = Event()
        
        if target_dt_str in daily_short: # 0~3일 단기
            d = daily_short[target_dt_str]
            event.add('summary', f"{get_emoji(None, None, None)} {min(d['tmps'])}° / {max(d['tmps'])}°")
            event.add('description', "\n".join(d['details']))
        elif target_dt_str in mid_forecast: # 4~10일 중기
            m = mid_forecast[target_dt_str]
            event.add('summary', f"{get_emoji(None, None, m['wf'])} {m['tmin']}° / {m['tmax']}°")
            event.add('description', f"오전/오후 예보: {m['wf']}\n(중기예보 데이터)")
        
        event.add('dtstart', target_dt_obj.date())
        event.add('dtend', target_dt_obj.date() + timedelta(days=1))
        cal.add_component(event)

    with open('weather.ics', 'wb') as f:
        f.write(cal.to_ical())
    print("Successfully updated weather.ics with Mid-term forecast")

if __name__ == "__main__":
    main()
