"""Interpret the council's published dates without inventing cancellations."""
from datetime import date, timedelta

SERVICES = {'recycling-collection-service': 'blue',
            'domestic-waste-collection-service': 'black'}

def collection_for(payload, target):
    settings = [item.get('settings', {}) for item in payload
                if isinstance(item, dict) and item.get('command') == 'settings']
    calendars = [item['collection_dates'] for item in settings if 'collection_dates' in item]
    if len(calendars) != 1 or not isinstance(calendars[0], dict):
        raise ValueError('Council returned an unreadable collection calendar')
    calendar = calendars[0]
    key = f'{target.month}_{target.year}'
    if key not in calendar:
        raise ValueError('Council has not published this month')
    rows = []
    for month in calendar.values():
        if not isinstance(month, list):
            raise ValueError('Council calendar format changed')
        for event in month:
            day = date.fromisoformat(event['date'])
            rows.append((day, event.get('service-identifier', '')))
    bins = {SERVICES[service] for day, service in rows
            if day == target and service in SERVICES}
    if len(bins) == 1:
        return bins.pop()
    if len(bins) > 1:
        raise ValueError('Both blue and black collections are listed; check the council')
    if any(day == target for day, _ in rows):
        raise ValueError('Other services are listed but no blue/black bin; check the council')
    # Erewash explicitly warns that blank Christmas dates can be unpublished.
    # A blank holiday date cannot be labelled as a confirmed cancellation.
    if (target.month == 12 and target.day >= 20) or (target.month == 1 and target.day <= 7):
        raise ValueError('Christmas/New Year dates are unconfirmed; check the council notice')
    # Require nearby actual bin dates either side, rather than an empty feed.
    before = any(target-timedelta(days=8) <= day < target and service in SERVICES for day, service in rows)
    after = any(target < day <= target+timedelta(days=8) and service in SERVICES for day, service in rows)
    if before and after:
        return 'none'
    raise ValueError('No confirmed collection or cancellation for this date')


def collection_from_events(events,blue_keywords,black_keywords):
    """Only consume a successfully fetched collection-only calendar."""
    if not isinstance(events,list):raise ValueError('Calendar returned no readable event list')
    if not events:return 'none'
    kinds=set()
    for event in events:
        if not isinstance(event,dict):raise ValueError('Unreadable collection event')
        text=(str(event.get('summary',''))+' '+str(event.get('description',''))).casefold()
        matched={kind for kind,words in [('blue',blue_keywords),('black',black_keywords)]
                 if any(word.strip() and word.casefold() in text for word in words)}
        if len(matched)!=1:raise ValueError('Collection event is ambiguous; no bin picture was guessed')
        kinds.update(matched)
    if len(kinds)!=1:raise ValueError('Both bin types are scheduled; check your calendar')
    return kinds.pop()
