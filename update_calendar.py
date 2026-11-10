import os
import sys
import requests
import pytz
from datetime import datetime, timedelta, timezone
from icalendar import Calendar, Event

# --- [1. 설정] ---
NX = int(os.environ.get('KMA_NX') or 63)
NY = int(os.environ.get('KMA_NY') or 88)
LOCATION_NAME = os.environ.get('LOCATION_NAME') or '삼천동'
REG_ID_TEMP = os.environ.get('REG_ID_TEMP') or '11F10201'
REG_ID_LAND = os.environ.get('REG_ID_LAND') or '11F10000'
API_KEY = os.environ.get('KMA_API_KEY', '').strip()

def get_weather_info(sky, pty):
    sky, pty = str(sky), str(pty)
    if pty == '1': return "🌧️", "비"
    if pty == '2': return "🌨️", "비/눈(진눈깨비)"
    if pty == '3': return "❄️", "눈"
    if pty == '4': return "☔", "소나기"
    if pty == '5': return "💧", "빗방울"
    if pty == '6': return "🌨️", "빗방울/눈날림"
    if pty == '7': return "❄️", "눈날림"
    if sky == '1': return "☀️", "맑음"
    if sky == '3': return "⛅", "구름많음"
    if sky == '4': return "☁️", "흐림"
    return "🌡️", "정보없음"

def get_mid_emoji(wf):
    if not wf: return "🌡️"
    wf = wf.replace(" ", "")
    if '소나기' in wf: return "☔"
    if '비' in wf: return "🌧️"
    if '눈' in wf or '진눈깨비' in wf: return "🌨️"
    if '구름많음' in wf: return "⛅"
    if '흐림' in wf: return "☁️"
    if '맑음' in wf: return "☀️"
    return "☀️"

def fetch_api(url, retries=1, timeout=10):
    # IP 차단성 문제라면 같은 러너 안에서 재시도해봐야 어차피 같은 IP라 소용없음.
    # 대신 워크플로우(matrix)에서 job 자체를 여러 러너로 병렬 실행해 다른 IP를 노림.
    # 그래서 여기서는 재시도를 최소화하고(기본 1회), 타임아웃도 짧게(10초) 잡아
    # 막힌 경우 오래 붙잡혀있지 않고 빨리 실패 판정하고 넘어가게 한다.
    safe_url = url.split('&authKey=')[0] + '&authKey=***'
    for attempt in range(1, retries + 1):
        try:
            res = requests.get(url, timeout=timeout)
            if res.status_code != 200:
                print(f"[API FAIL] attempt={attempt}/{retries} status={res.status_code} url={safe_url} body={res.text[:300]}")
            else:
                data = res.json()
                result_code = data.get('response', {}).get('header', {}).get('resultCode')
                if result_code == '00':
                    return data
                result_msg = data.get('response', {}).get('header', {}).get('resultMsg')
                print(f"[API FAIL] attempt={attempt}/{retries} resultCode={result_code} resultMsg={result_msg} url={safe_url}")
        except Exception as e:
            print(f"[API EXCEPTION] attempt={attempt}/{retries} {type(e).__name__}: {e} url={safe_url}")

    print(f"[API GIVEUP] {retries}회 시도 모두 실패 url={safe_url}")
    return None

def get_base_datetime(now):
    release_hours = [2, 5, 8, 11, 14, 17, 20, 23]
    effective_now = now - timedelta(minutes=10)
    valid = [h for h in release_hours if h <= effective_now.hour]
    if valid:
        base_h = max(valid)
        return effective_now.strftime('%Y%m%d'), f"{base_h:02d}00"
    else:
        prev = effective_now - timedelta(days=1)
        return prev.strftime('%Y%m%d'), "2300"

def get_tmfc_candidates(now):
    candidates = []
    effective_now = now - timedelta(minutes=30)
    if effective_now.hour < 6:
        c1 = (effective_now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        c2 = (effective_now - timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0)
    elif effective_now.hour < 18:
        c1 = effective_now.replace(hour=6, minute=0, second=0, microsecond=0)
        c2 = (effective_now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    else:
        c1 = effective_now.replace(hour=18, minute=0, second=0, microsecond=0)
        c2 = effective_now.replace(hour=6, minute=0, second=0, microsecond=0)
    candidates.append(c1)
    candidates.append(c2)
    return candidates

def load_cached_events(ics_path):
    """기존 weather.ics에서 날짜별 이벤트를 raw 바이트로 캐싱"""
    cache = {}
    if not os.path.exists(ics_path):
        return cache
    try:
        with open(ics_path, 'rb') as f:
            cal = Calendar.from_ical(f.read())
        for component in cal.walk():
            if component.name == 'VEVENT':
                dtstart = component.get('dtstart')
                if dtstart:
                    d = dtstart.dt
                    if hasattr(d, 'strftime'):
                        d_str = d.strftime('%Y%m%d')
                        cache[d_str] = component.to_ical()
    except:
        pass
    return cache

def event_from_cache(raw_ical):
    """raw 바이트에서 VEVENT 객체를 새로 파싱해서 반환"""
    try:
        wrapped = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + raw_ical + b"\r\nEND:VCALENDAR"
        cal = Calendar.from_ical(wrapped)
        for component in cal.walk():
            if component.name == 'VEVENT':
                if not component.get('dtstamp'):
                    component.add('dtstamp', datetime.now(timezone.utc))
                return component
    except Exception as exc:
        print(f'[CACHE WARN] {type(exc).__name__}: {exc}')
    return None

def main():
    if not API_KEY:
        print('::error::KMA_API_KEY GitHub Secret이 설정되지 않았습니다.')
        sys.exit(2)
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.now(seoul_tz)
    today_str = now.strftime('%Y%m%d')
    update_ts = now.strftime('%Y-%m-%d %H:%M:%S')

    today_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    short_end_str = (today_dt + timedelta(days=3)).strftime('%Y%m%d')  # D+0~D+3 단기
    mid_start_dt  = today_dt + timedelta(days=4)                        # D+4부터 중기
    mid_end_dt    = get_tmfc_candidates(now)[0] + timedelta(days=10)  # 최신 중기발표 D+10까지

    cal = Calendar()
    cal.add('prodid', '-//Adamkk111//KMA Weather Calendar//KO')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('X-WR-CALNAME', '기상청 날씨')
    cal.add('X-WR-TIMEZONE', 'Asia/Seoul')
    processed_dates = set()
    api_fallback_occurred = False

    # --- [2. 기존 캐시 로드] ---
    cached_events = load_cached_events('weather.ics')
    print("캐시된 날짜들:", sorted(cached_events.keys()))

    # --- [3. 단기 예보: D+0 ~ D+3 시간별 상세] ---
    base_date, base_time = get_base_datetime(now)
    print(f"[단기예보] 요청 base_date={base_date} base_time={base_time} (now={now.strftime('%Y-%m-%d %H:%M:%S')})")
    url_short = (
        f"https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
        f"?dataType=JSON&base_date={base_date}&base_time={base_time}"
        f"&nx={NX}&ny={NY}&numOfRows=1000&authKey={API_KEY}"
    )
    forecast_map = {}
    short_res = fetch_api(url_short)
    if short_res is None:
        print(f"[단기예보] API 실패 (base_date={base_date}, base_time={base_time}) -> 캐시 재사용 예정")
        api_fallback_occurred = True
    if short_res and 'body' in short_res['response']:
        for it in short_res['response']['body']['items']['item']:
            d, t, cat, val = it['fcstDate'], it['fcstTime'], it['category'], it['fcstValue']
            if d not in forecast_map: forecast_map[d] = {}
            if t not in forecast_map[d]: forecast_map[d][t] = {}
            forecast_map[d][t][cat] = val

    cache = {'TMP': '15', 'SKY': '1', 'PTY': '0', 'REH': '50', 'WSD': '1.0', 'POP': '0'}
    for d_str in sorted(forecast_map.keys()):
        if d_str < today_str or d_str > short_end_str:
            continue
        day_data = forecast_map[d_str]
        tmps = [float(day_data[t]['TMP']) for t in day_data if 'TMP' in day_data[t]]
        if not tmps: continue
        t_min, t_max = int(min(tmps)), int(max(tmps))
        rep_t = '1200' if '1200' in day_data else sorted(day_data.keys())[0]
        rep_emoji, _ = get_weather_info(
            day_data[rep_t].get('SKY', cache['SKY']),
            day_data[rep_t].get('PTY', cache['PTY'])
        )
        desc = []
        has_future_data = False
        for h in range(24):
            t_str = f"{h:02d}00"
            event_time = seoul_tz.localize(datetime.strptime(f"{d_str}{t_str}", '%Y%m%d%H%M'))
            if t_str in day_data:
                for cat in cache.keys():
                    if cat in day_data[t_str]: cache[cat] = day_data[t_str][cat]
            if event_time >= now:
                emoji, wf_str = get_weather_info(cache['SKY'], cache['PTY'])
                details = []
                if cache['PTY'] != '0':
                    details.append(f"☔{cache['POP']}%")
                details.append(f"💧{cache['REH']}%")
                details.append(f"🚩{cache['WSD']}m/s")
                desc.append(f"[{t_str[:2]}시] {emoji} {wf_str} {cache['TMP']}°C ({' '.join(details)})")
                has_future_data = True
        if not has_future_data: continue
        event = Event()
        event.add('dtstamp', datetime.now(timezone.utc))
        event.add('summary', f"{rep_emoji} {t_min}°C/{t_max}°C")
        event.add('location', LOCATION_NAME)
        desc.append(f"\n최종 업데이트: {update_ts} (KST)")
        event.add('description', "\n".join(desc))
        event.add('dtstart', datetime.strptime(d_str, '%Y%m%d').date())
        event.add('dtend', datetime.strptime(d_str, '%Y%m%d').date() + timedelta(days=1))
        event.add('uid', f"{d_str}@short_summary")
        cal.add_component(event)
        processed_dates.add(d_str)

    # 단기 API 실패시 D+0~D+3 캐시 재사용
    for delta in range(4):
        d_str = (today_dt + timedelta(days=delta)).strftime('%Y%m%d')
        if d_str not in processed_dates and d_str in cached_events:
            event = event_from_cache(cached_events[d_str])
            if event:
                cal.add_component(event)
                processed_dates.add(d_str)

    # --- [4. 중기 예보: D+4 ~ D+10] ---
    tmfc_candidates = get_tmfc_candidates(now)
    t_res, l_res, tm_fc_dt = None, None, None
    for candidate in tmfc_candidates:
        tm_fc_str = candidate.strftime('%Y%m%d%H%M')
        url_mid_temp = (
            f"https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidTa"
            f"?dataType=JSON&regId={REG_ID_TEMP}&tmFc={tm_fc_str}&authKey={API_KEY}"
        )
        url_mid_land = (
            f"https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidLandFcst"
            f"?dataType=JSON&regId={REG_ID_LAND}&tmFc={tm_fc_str}&authKey={API_KEY}"
        )
        t_try = fetch_api(url_mid_temp)
        if t_try is None:
            print(f"[중기예보] tmFc={tm_fc_str} 온도 API 실패 -> 육상 API 호출은 생략하고 다음 후보로")
            continue
        l_try = fetch_api(url_mid_land)
        if t_try and l_try:
            t_res, l_res, tm_fc_dt = t_try, l_try, candidate
            break

    if tm_fc_dt is None:
        print(f"[중기예보] 후보 tmFc {[c.strftime('%Y%m%d%H%M') for c in tmfc_candidates]} 전부 실패 -> 캐시 재사용 예정")
        api_fallback_occurred = True

    t_items, l_items = None, None
    if t_res and l_res and tm_fc_dt:
        try:
            t_items = t_res['response']['body']['items']['item'][0]
            l_items = l_res['response']['body']['items']['item'][0]
        except (KeyError, IndexError, TypeError) as e:
            print(f"[중기예보] 파싱 실패: {type(e).__name__}: {e}")
            api_fallback_occurred = True

    # D+4 ~ D+10 순서대로 채우기
    cur_dt = mid_start_dt
    while cur_dt <= mid_end_dt:
        d_str = cur_dt.strftime('%Y%m%d')
        event = None

        # 1순위: 새 중기 데이터
        if t_items and l_items and tm_fc_dt:
            field_i = (cur_dt.date() - tm_fc_dt.date()).days
            t_min = t_items.get(f'taMin{field_i}')
            t_max = t_items.get(f'taMax{field_i}')
            wf_rep = l_items.get(f'wf{field_i}Pm') if field_i <= 7 else l_items.get(f'wf{field_i}')

            if t_min is not None and t_max is not None and wf_rep is not None:
                mid_desc = []
                if field_i <= 7:
                    wf_am = l_items.get(f'wf{field_i}Am')
                    wf_pm = l_items.get(f'wf{field_i}Pm')
                    rn_am = l_items.get(f'rnSt{field_i}Am')
                    rn_pm = l_items.get(f'rnSt{field_i}Pm')
                    mid_desc.append(f"[오전] {get_mid_emoji(wf_am)} {wf_am} (☔{rn_am}%)")
                    mid_desc.append(f"[오후] {get_mid_emoji(wf_pm)} {wf_pm} (☔{rn_pm}%)")
                else:
                    wf_val = l_items.get(f'wf{field_i}')
                    rn_st  = l_items.get(f'rnSt{field_i}')
                    mid_desc.append(f"[종일] {get_mid_emoji(wf_val)} {wf_val} (☔{rn_st}%)")
                mid_desc.append(f"\n최종 업데이트: {update_ts} (KST)")

                event = Event()
                event.add('dtstamp', datetime.now(timezone.utc))
                event.add('summary', f"{get_mid_emoji(wf_rep)} {t_min}°C/{t_max}°C")
                event.add('location', LOCATION_NAME)
                event.add('description', "\n".join(mid_desc))
                event.add('dtstart', cur_dt.date())
                event.add('dtend', (cur_dt + timedelta(days=1)).date())
                event.add('uid', f"{d_str}@mid")

        # 2순위: 캐시 재사용
        if event is None and d_str in cached_events:
            event = event_from_cache(cached_events[d_str])

        if event is not None:
            cal.add_component(event)
            processed_dates.add(d_str)

        cur_dt += timedelta(days=1)

    print("최종 processed_dates:", sorted(processed_dates))
    expected_dates = {(today_dt + timedelta(days=i)).strftime('%Y%m%d')
                      for i in range((mid_end_dt.date() - today_dt.date()).days + 1)}
    missing_dates = sorted(expected_dates - processed_dates)
    if missing_dates:
        print('::error::날씨 데이터가 없는 날짜: ' + ', '.join(missing_dates))
        print('[ABORT] 기존 weather.ics를 덮어쓰지 않습니다.')
        sys.exit(1)
    with open('weather.ics', 'wb') as f:
        f.write(cal.to_ical())

    if api_fallback_occurred:
        print("[결과] 일부 예보를 API에서 못 받아 캐시로 대체했습니다 (fallback 발생).")
        sys.exit(1)
    else:
        print("[결과] 모든 예보를 정상적으로 갱신했습니다.")
        sys.exit(0)

if __name__ == "__main__":
    main()
