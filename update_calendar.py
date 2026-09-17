import os
import sys
from datetime import datetime, timedelta

import pytz
import requests
from icalendar import Calendar, Event

NX = int(os.environ.get("KMA_NX", 60))
NY = int(os.environ.get("KMA_NY", 127))
LOCATION_NAME = os.environ.get("LOCATION_NAME", "우리집")
REG_ID_TEMP = os.environ.get("REG_ID_TEMP", "11B10101")
REG_ID_LAND = os.environ.get("REG_ID_LAND", "11B00000")
API_KEY = os.environ.get("KMA_API_KEY")

SEOUL_TZ = pytz.timezone("Asia/Seoul")
SHORT_RELEASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
SHORT_ENDPOINT = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
MID_TEMP_ENDPOINT = "https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidTa"
MID_LAND_ENDPOINT = "https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidLandFcst"


def get_weather_info(sky, pty):
    sky, pty = str(sky), str(pty)
    precipitation = {
        "1": ("🌧️", "비"),
        "2": ("🌨️", "비/눈(진눈깨비)"),
        "3": ("❄️", "눈"),
        "4": ("☔", "소나기"),
        "5": ("💧", "빗방울"),
        "6": ("🌨️", "빗방울/눈날림"),
        "7": ("❄️", "눈날림"),
    }
    if pty in precipitation:
        return precipitation[pty]
    return {
        "1": ("☀️", "맑음"),
        "3": ("⛅", "구름많음"),
        "4": ("☁️", "흐림"),
    }.get(sky, ("🌡️", "정보없음"))


def get_mid_emoji(weather):
    if not weather:
        return "🌡️"
    text = str(weather).replace(" ", "")
    if "소나기" in text:
        return "☔"
    if "진눈깨비" in text:
        return "🌨️"
    if "눈" in text:
        return "❄️"
    if "비" in text:
        return "🌧️"
    if "구름많음" in text:
        return "⛅"
    if "흐림" in text:
        return "☁️"
    if "맑음" in text:
        return "☀️"
    return "🌡️"


def fetch_api(endpoint, params, retries=1, timeout=10):
    safe_params = {**params, "authKey": "***"}
    last_error = "unknown error"
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            header = data.get("response", {}).get("header", {})
            result_code = str(header.get("resultCode", ""))
            result_msg = header.get("resultMsg", "")
            if result_code == "00":
                return data
            last_error = f"resultCode={result_code}, resultMsg={result_msg}"
            print(f"[API FAIL] {attempt}/{retries} {last_error} endpoint={endpoint} params={safe_params}")
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"[API EXCEPTION] {attempt}/{retries} {last_error} endpoint={endpoint} params={safe_params}")
    print(f"[API GIVEUP] {last_error} endpoint={endpoint}")
    return None


def get_short_base_datetime(now):
    effective_now = now - timedelta(minutes=10)
    valid_hours = [hour for hour in SHORT_RELEASE_HOURS if hour <= effective_now.hour]
    if valid_hours:
        return effective_now.strftime("%Y%m%d"), f"{max(valid_hours):02d}00"
    previous_day = effective_now - timedelta(days=1)
    return previous_day.strftime("%Y%m%d"), "2300"


def get_mid_tmfc_candidates(now):
    # 최근 발표분이 부분적으로만 채워지는 경우가 있어 최근 24시간 발표분을 모두 후보로 둔다.
    cutoff = now - timedelta(minutes=30)
    oldest = cutoff - timedelta(hours=24)
    candidates = []
    day = (cutoff - timedelta(days=1)).date()
    while day <= cutoff.date():
        for hour in (6, 18):
            candidate = SEOUL_TZ.localize(datetime.combine(day, datetime.min.time()).replace(hour=hour))
            if oldest <= candidate <= cutoff:
                candidates.append(candidate)
        day += timedelta(days=1)
    return sorted(candidates, reverse=True)


def extract_first_item(data):
    if not data:
        return None
    try:
        items = data["response"]["body"]["items"]["item"]
        return items[0] if items else None
    except (KeyError, IndexError, TypeError):
        return None


def load_cached_events(path):
    cached = {}
    if not os.path.exists(path):
        return cached
    try:
        with open(path, "rb") as file:
            calendar = Calendar.from_ical(file.read())
        for component in calendar.walk("VEVENT"):
            dtstart = component.get("dtstart")
            if not dtstart:
                continue
            value = dtstart.dt
            if isinstance(value, datetime):
                value = value.date()
            cached[value.strftime("%Y%m%d")] = component.to_ical()
    except Exception as exc:
        print(f"[CACHE WARN] 기존 ICS 파싱 실패: {type(exc).__name__}: {exc}")
    return cached


def event_from_cache(raw_ical):
    try:
        wrapped = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + raw_ical + b"\r\nEND:VCALENDAR\r\n"
        calendar = Calendar.from_ical(wrapped)
        events = calendar.walk("VEVENT")
        return events[0] if events else None
    except Exception as exc:
        print(f"[CACHE WARN] 캐시 이벤트 복원 실패: {type(exc).__name__}: {exc}")
        return None


def add_cached_event(calendar, cached_events, date_str, processed_dates):
    raw = cached_events.get(date_str)
    if not raw:
        return False
    event = event_from_cache(raw)
    if event is None:
        return False
    summary = str(event.get("summary", ""))
    if not summary or any(token in summary.lower() for token in ("none", "null", "nan", "정보없음")):
        print(f"[CACHE WARN] {date_str} 캐시에 잘못된 값이 있어 무시합니다: {summary}")
        return False
    calendar.add_component(event)
    processed_dates.add(date_str)
    return True


def parse_short_forecast(data):
    result = {}
    if not data:
        return result
    try:
        items = data["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return result
    for item in items or []:
        try:
            date_str = item["fcstDate"]
            time_str = item["fcstTime"]
            category = item["category"]
            value = item["fcstValue"]
        except KeyError:
            continue
        result.setdefault(date_str, {}).setdefault(time_str, {})[category] = value
    return result


def make_short_event(target_date, day_data, now, update_ts):
    temperatures = []
    for hourly in day_data.values():
        if "TMP" in hourly:
            try:
                temperatures.append(float(hourly["TMP"]))
            except (TypeError, ValueError):
                pass
    if not temperatures or not day_data:
        return None

    sorted_times = sorted(day_data.keys())
    representative_time = "1200" if "1200" in day_data else sorted_times[0]
    representative = day_data[representative_time]
    representative_emoji, _ = get_weather_info(representative.get("SKY", "1"), representative.get("PTY", "0"))

    state = {"TMP": None, "SKY": "1", "PTY": "0", "REH": None, "WSD": None, "POP": "0"}
    description = []
    for time_str in sorted_times:
        hourly = day_data[time_str]
        for category in state:
            if category in hourly:
                state[category] = hourly[category]
        try:
            event_time = SEOUL_TZ.localize(datetime.strptime(target_date.strftime("%Y%m%d") + time_str, "%Y%m%d%H%M"))
        except ValueError:
            continue
        if event_time < now or state["TMP"] is None:
            continue
        emoji, weather_text = get_weather_info(state["SKY"], state["PTY"])
        details = []
        if state["PTY"] != "0":
            details.append(f"☔{state['POP']}%")
        if state["REH"] is not None:
            details.append(f"💧{state['REH']}%")
        if state["WSD"] is not None:
            details.append(f"🚩{state['WSD']}m/s")
        detail_text = f" ({' '.join(details)})" if details else ""
        description.append(f"[{time_str[:2]}시] {emoji} {weather_text} {state['TMP']}°C{detail_text}")

    event = Event()
    event.add("summary", f"{representative_emoji} {int(min(temperatures))}°C/{int(max(temperatures))}°C")
    event.add("location", LOCATION_NAME)
    if description:
        description.append(f"\n최종 업데이트: {update_ts} (KST)")
        event.add("description", "\n".join(description))
    event.add("dtstart", target_date)
    event.add("dtend", target_date + timedelta(days=1))
    event.add("uid", f"{target_date.strftime('%Y%m%d')}@short-summary")
    return event


def get_mid_missing_fields(target_date, tmfc_date, temp_items, land_items):
    field_index = (target_date - tmfc_date).days
    if field_index < 4 or field_index > 10:
        return [f"field_index={field_index}"]
    missing = []
    for key in (f"taMin{field_index}", f"taMax{field_index}"):
        if temp_items.get(key) is None:
            missing.append(key)
    if field_index <= 7:
        keys = (f"wf{field_index}Am", f"wf{field_index}Pm", f"rnSt{field_index}Am", f"rnSt{field_index}Pm")
    else:
        keys = (f"wf{field_index}", f"rnSt{field_index}")
    for key in keys:
        if land_items.get(key) is None:
            missing.append(key)
    return missing


def make_mid_event(target_date, tmfc_date, temp_items, land_items, update_ts):
    field_index = (target_date - tmfc_date).days
    if get_mid_missing_fields(target_date, tmfc_date, temp_items, land_items):
        return None
    temp_min = temp_items[f"taMin{field_index}"]
    temp_max = temp_items[f"taMax{field_index}"]
    if field_index <= 7:
        weather_am = land_items[f"wf{field_index}Am"]
        weather_pm = land_items[f"wf{field_index}Pm"]
        rain_am = land_items[f"rnSt{field_index}Am"]
        rain_pm = land_items[f"rnSt{field_index}Pm"]
        representative_weather = weather_pm or weather_am
        lines = [
            f"[오전] {get_mid_emoji(weather_am)} {weather_am} (☔{rain_am}%)",
            f"[오후] {get_mid_emoji(weather_pm)} {weather_pm} (☔{rain_pm}%)",
        ]
    else:
        weather_day = land_items[f"wf{field_index}"]
        rain_day = land_items[f"rnSt{field_index}"]
        representative_weather = weather_day
        lines = [f"[종일] {get_mid_emoji(weather_day)} {weather_day} (☔{rain_day}%)"]
    lines.append(f"\n최종 업데이트: {update_ts} (KST)")
    event = Event()
    event.add("summary", f"{get_mid_emoji(representative_weather)} {temp_min}°C/{temp_max}°C")
    event.add("location", LOCATION_NAME)
    event.add("description", "\n".join(lines))
    event.add("dtstart", target_date)
    event.add("dtend", target_date + timedelta(days=1))
    event.add("uid", f"{target_date.strftime('%Y%m%d')}@mid")
    return event


def fetch_mid_datasets(now):
    datasets = []
    for candidate in get_mid_tmfc_candidates(now):
        tmfc = candidate.strftime("%Y%m%d%H%M")
        print(f"[MID] tmFc={tmfc} 시도")
        common = {"dataType": "JSON", "tmFc": tmfc, "authKey": API_KEY, "pageNo": 1, "numOfRows": 10}
        temp_response = fetch_api(MID_TEMP_ENDPOINT, {**common, "regId": REG_ID_TEMP})
        land_response = fetch_api(MID_LAND_ENDPOINT, {**common, "regId": REG_ID_LAND})
        temp_items = extract_first_item(temp_response)
        land_items = extract_first_item(land_response)
        if not temp_items or not land_items:
            print(f"[MID] tmFc={tmfc} 응답 본문이 비어 있어 다음 후보로 넘어갑니다.")
            continue
        datasets.append({"tmfc": candidate, "temp": temp_items, "land": land_items})
    return datasets


def main():
    if not API_KEY:
        print("::error::KMA_API_KEY GitHub Secret이 설정되어 있지 않습니다.")
        return 2

    now = datetime.now(SEOUL_TZ)
    today = now.date()
    update_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    calendar = Calendar()
    calendar.add("prodid", "-//Adamkk111//KMA Weather Calendar//KO")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("X-WR-CALNAME", "기상청 날씨")
    calendar.add("X-WR-TIMEZONE", "Asia/Seoul")

    cached_events = load_cached_events("weather.ics")
    processed_dates = set()
    used_cache_dates = []
    used_mid_issue_by_date = {}

    print(f"[START] {update_ts} KST")
    print("[CONFIG] weather coordinates and region IDs loaded")

    base_date, base_time = get_short_base_datetime(now)
    print(f"[SHORT] base_date={base_date} base_time={base_time}")
    short_response = fetch_api(SHORT_ENDPOINT, {
        "dataType": "JSON", "base_date": base_date, "base_time": base_time,
        "nx": NX, "ny": NY, "numOfRows": 1000, "authKey": API_KEY,
    })
    forecast_map = parse_short_forecast(short_response)

    for delta in range(4):
        target_date = today + timedelta(days=delta)
        date_str = target_date.strftime("%Y%m%d")
        event = make_short_event(target_date, forecast_map.get(date_str, {}), now, update_ts)
        if event is not None:
            calendar.add_component(event)
            processed_dates.add(date_str)
        elif add_cached_event(calendar, cached_events, date_str, processed_dates):
            used_cache_dates.append(date_str)
            print(f"[SHORT CACHE] {date_str}")
        else:
            print(f"::error::단기예보 {date_str}의 새 데이터와 정상 캐시가 모두 없습니다.")

    mid_datasets = fetch_mid_datasets(now)
    for delta in range(4, 11):
        target_date = today + timedelta(days=delta)
        date_str = target_date.strftime("%Y%m%d")
        event = None

        for dataset in mid_datasets:
            missing = get_mid_missing_fields(target_date, dataset["tmfc"].date(), dataset["temp"], dataset["land"])
            if missing:
                print(f"[MID INCOMPLETE] {date_str} tmFc={dataset['tmfc'].strftime('%Y%m%d%H%M')} missing={','.join(missing)}")
                continue
            event = make_mid_event(target_date, dataset["tmfc"].date(), dataset["temp"], dataset["land"], update_ts)
            if event is not None:
                used_mid_issue_by_date[date_str] = dataset["tmfc"].strftime("%Y%m%d%H%M")
                break

        # 중기 D+4가 비어 있는 경우 단기예보에 해당 날짜가 있으면 연결 구간으로 사용한다.
        if event is None and date_str in forecast_map:
            event = make_short_event(target_date, forecast_map[date_str], now, update_ts)
            if event is not None:
                print(f"[MID->SHORT FALLBACK] {date_str}")

        if event is not None:
            calendar.add_component(event)
            processed_dates.add(date_str)
        elif add_cached_event(calendar, cached_events, date_str, processed_dates):
            used_cache_dates.append(date_str)
            print(f"[MID CACHE] {date_str}")
        else:
            print(f"::error::중기예보 {date_str}의 새 데이터와 정상 캐시가 모두 없습니다.")

    expected_dates = {(today + timedelta(days=delta)).strftime("%Y%m%d") for delta in range(11)}
    missing_dates = sorted(expected_dates - processed_dates)
    if missing_dates:
        print(f"::error::날씨 이벤트가 없는 날짜: {', '.join(missing_dates)}")
        print("[ABORT] 불완전한 weather.ics로 기존 파일을 덮어쓰지 않습니다.")
        return 1

    output = calendar.to_ical()
    output_lower = output.lower()
    if b"none" in output_lower or b"nan" in output_lower:
        print("::error::생성 결과에서 잘못된 None/NaN 값이 발견되었습니다.")
        print("[ABORT] 기존 weather.ics를 유지합니다.")
        return 1

    with open("weather.ics", "wb") as file:
        file.write(output)

    if used_mid_issue_by_date:
        print("[MID USED] " + ", ".join(f"{date}:{issue}" for date, issue in sorted(used_mid_issue_by_date.items())))
    if used_cache_dates:
        print("[CACHE USED] " + ", ".join(sorted(set(used_cache_dates))))
    print(f"[DONE] {len(processed_dates)}일치 weather.ics 생성 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())