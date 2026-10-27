-- Stations à rééquilibrer maintenant : vides ou pleines depuis au moins 30 minutes,
-- hors stations déjà en anomalie technique (un camion n'y changerait rien).
with last_hour as (
    select
        station_id,
        avgIf(avg_bikes, bucket >= (select max(bucket) from {{ ref('int_station_status_15min') }}) - interval 30 minute) as bikes_now,
        avgIf(avg_docks, bucket >= (select max(bucket) from {{ ref('int_station_status_15min') }}) - interval 30 minute) as docks_now
    from {{ ref('int_station_status_15min') }}
    where bucket >= (select max(bucket) from {{ ref('int_station_status_15min') }}) - interval 1 hour
    group by station_id
)
select
    d.station_id                                   as station_id,
    d.station_code                                 as station_code,
    d.station_name                                 as station_name,
    d.capacity                                     as capacity,
    d.lat                                          as lat,
    d.lon                                          as lon,
    if(l.bikes_now < {{ var('near_threshold') }}, 'apporter des vélos', 'retirer des vélos') as action,
    -- objectif : ramener la station à mi-capacité
    toUInt16(round(abs(d.capacity / 2 - l.bikes_now))) as bikes_to_move,
    d.usage_profile                                as usage_profile
from last_hour as l
inner join {{ ref('dim_station') }} as d on d.station_id = l.station_id
where (l.bikes_now < {{ var('near_threshold') }} or l.docks_now < {{ var('near_threshold') }})
  and l.station_id not in (
      select station_id from {{ ref('mart_station_anomalies') }}
      where anomaly_type in ('STALE_DATA', 'OUT_OF_SERVICE', 'DOCKS_UNAVAILABLE')
  )
order by bikes_to_move desc
