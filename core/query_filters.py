"""Whitelisted, parameterized query tools for database and log viewers."""
import datetime
import math
from sqlalchemy import String, cast, or_


def browse_query(model, columns, args, default_sort='timestamp', default_direction='desc'):
    query = model.query
    search = str(args.get('q', '')).strip()
    if len(search) > 200:
        raise ValueError('Search text must not exceed 200 characters')
    if search:
        query = query.filter(or_(*[
            cast(getattr(model, name), String).contains(search, autoescape=True)
            for name in columns
        ]))

    start, end = args.get('start'), args.get('end')
    if start or end:
        if 'timestamp' not in columns:
            raise ValueError('This table has no timestamp column')
        dates = {}
        for name, value in [('start', start), ('end', end)]:
            if value:
                try:
                    date = datetime.datetime.fromisoformat(value)
                    if date.tzinfo is not None:
                        raise ValueError
                    if name == 'end' and len(value) == 16:
                        date = date.replace(second=59, microsecond=999999)
                    dates[name] = date
                except ValueError:
                    raise ValueError('Invalid local date/time range')
        if len(dates) == 2 and dates['start'] > dates['end']:
            raise ValueError('Start time must not exceed end time')
        if 'start' in dates:
            query = query.filter(model.timestamp >= dates['start'])
        if 'end' in dates:
            query = query.filter(model.timestamp <= dates['end'])

    column = args.get('filter_column')
    if column:
        if column not in columns:
            raise ValueError('Unknown filter column')
        attr = getattr(model, column)
        operation = args.get('filter_op', 'eq')
        value = args.get('filter_value', '')
        if operation in ('null', 'notnull'):
            query = query.filter(attr.is_(None) if operation == 'null' else attr.is_not(None))
        elif operation == 'contains':
            query = query.filter(cast(attr, String).contains(value, autoescape=True))
        elif operation in ('eq', 'gte', 'lte'):
            try:
                kind = attr.property.columns[0].type.python_type
                value = datetime.datetime.fromisoformat(value) if kind is datetime.datetime else kind(value)
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError('Invalid value for the selected column')
            query = query.filter({'eq': attr == value, 'gte': attr >= value, 'lte': attr <= value}[operation])
        else:
            raise ValueError('Unknown filter operation')

    for name in ('level', 'source'):
        value = args.get(name)
        if value:
            if name not in columns:
                raise ValueError('Unsupported log filter')
            attr = getattr(model, name)
            query = query.filter(or_(attr.is_(None), attr == 'legacy')
                                 if name == 'source' and value == 'legacy' else attr == value)
    sort = args.get('sort') or default_sort
    direction = args.get('direction') or default_direction
    if sort not in columns or direction not in ('asc', 'desc'):
        raise ValueError('Invalid sort column or direction')
    attr = getattr(model, sort)
    query = query.order_by(attr.asc() if direction == 'asc' else attr.desc())
    primary_key = model.__mapper__.primary_key[0].key
    if primary_key != sort:
        query = query.order_by(getattr(model, primary_key).asc() if direction == 'asc'
                               else getattr(model, primary_key).desc())
    return query
