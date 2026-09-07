"""
Weather ticket generator using wttr.in for Fun Print thermal printers.
"""

import json
import urllib.parse
import urllib.request
from PIL import Image, ImageDraw, ImageFont

from .protocol import PRINTER_WIDTH


def fetch_weather_ticket(city: str = "Rennes") -> Image.Image:
    """
    Fetches live weather from wttr.in and renders a 384px wide thermal ticket.
    """
    encoded_city = urllib.parse.quote(city)
    url = f"http://wttr.in/{encoded_city}?format=j1"
    req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
    
    with urllib.request.urlopen(req, timeout=6.0) as resp:
        data = json.loads(resp.read().decode('utf-8'))

    # Fetch ASCII art icon
    ascii_art = "   \\  /   \n    .-.   \n ― (   ) ―\n    `-’   \n   /  \\   "
    try:
        req_ascii = urllib.request.Request(f"http://wttr.in/{encoded_city}?0&T", headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req_ascii, timeout=5.0) as resp:
            raw_txt = resp.read().decode('utf-8', errors='ignore')
            art_lines = [line[:16] for line in raw_txt.split('\n')[2:7] if line.strip()]
            if art_lines:
                ascii_art = "\n".join(art_lines)
    except Exception:
        pass

    current = data['current_condition'][0]
    weather_today = data['weather'][0]
    weather_tomorrow = data['weather'][1]
    nearest = data['nearest_area'][0]

    city_name = nearest['areaName'][0]['value']
    region_name = nearest['region'][0]['value']
    country_name = nearest['country'][0]['value']
    location_str = f"{city_name}, {region_name}, {country_name}"

    temp_c = current['temp_C']
    feels_c = current['FeelsLikeC']
    desc = current['weatherDesc'][0]['value']
    humidity = current['humidity']
    wind_spd = current['windspeedKmph']
    wind_dir = current['winddir16Point']
    pressure = current['pressure']

    width = PRINTER_WIDTH
    height = 680
    img = Image.new('L', (width, height), color=255)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([(10, 10), (width - 10, 50)], fill=0)
    draw.text((55, 20), f"★ WEATHER: {city_name.upper()} ★", fill=255)

    draw.text((20, 65), f"Location: {location_str}", fill=0)
    draw.text((20, 85), f"Date: {weather_today['date']}  |  Observed: {current['observation_time']}", fill=0)
    draw.line([(10, 110), (width - 10, 110)], fill=0, width=1)

    # Current conditions
    draw.text((20, 125), f"NOW: {desc.upper()}", fill=0)
    draw.text((20, 150), f"Temperature: {temp_c}°C (Feels {feels_c}°C)", fill=0)
    draw.text((20, 175), f"Wind: {wind_dir} {wind_spd} km/h", fill=0)
    draw.text((20, 195), f"Humidity: {humidity}%  |  Pressure: {pressure}hPa", fill=0)

    # ASCII Icon
    draw.rectangle([(width - 140, 120), (width - 20, 215)], outline=0, width=1)
    draw.text((width - 130, 130), ascii_art, fill=0)

    draw.line([(10, 230), (width - 10, 230)], fill=0, width=1)

    # Today's Breakdown
    draw.text((20, 245), "[ TODAY'S FORECAST ]", fill=0)
    draw.text((30, 270), f"Max: {weather_today['maxtempC']}°C   Min: {weather_today['mintempC']}°C   UV: {weather_today['uvIndex']}", fill=0)
    draw.text((30, 290), f"Sun: ↑ {weather_today['astronomy'][0]['sunrise']}  ↓ {weather_today['astronomy'][0]['sunset']}", fill=0)

    # Hourly
    draw.line([(20, 320), (width - 20, 320)], fill=0, width=1)
    draw.text((25, 330), "Morning:  " + weather_today['hourly'][2]['tempC'] + "°C  " + weather_today['hourly'][2]['weatherDesc'][0]['value'], fill=0)
    draw.text((25, 355), "Noon:     " + weather_today['hourly'][4]['tempC'] + "°C  " + weather_today['hourly'][4]['weatherDesc'][0]['value'], fill=0)
    draw.text((25, 380), "Evening:  " + weather_today['hourly'][6]['tempC'] + "°C  " + weather_today['hourly'][6]['weatherDesc'][0]['value'], fill=0)
    draw.text((25, 405), "Night:    " + weather_today['hourly'][7]['tempC'] + "°C  " + weather_today['hourly'][7]['weatherDesc'][0]['value'], fill=0)
    draw.line([(20, 435), (width - 20, 435)], fill=0, width=1)

    # Tomorrow
    draw.text((20, 455), "[ TOMORROW'S OUTLOOK ]", fill=0)
    draw.text((30, 480), f"Date: {weather_tomorrow['date']}", fill=0)
    draw.text((30, 505), f"Temp: {weather_tomorrow['mintempC']}°C - {weather_tomorrow['maxtempC']}°C", fill=0)
    desc_tom = weather_tomorrow['hourly'][4]['weatherDesc'][0]['value']
    draw.text((30, 530), f"Condition: {desc_tom}", fill=0)
    draw.text((30, 555), f"Sun: ↑ {weather_tomorrow['astronomy'][0]['sunrise']}  ↓ {weather_tomorrow['astronomy'][0]['sunset']}", fill=0)

    draw.line([(10, 590), (width - 10, 590)], fill=0, width=2)
    draw.text((45, 610), "Powered by wttr.in  •  Thermal Print", fill=0)

    return img
