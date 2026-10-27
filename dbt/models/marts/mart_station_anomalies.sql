-- Anomalies actives à la date du dernier relevé (et non à now() : le modèle se rejoue sur l'historique).
-- Une station figée est exclue des autres contrôles, ses valeurs n'étant plus fiables.
with
ref as (
    select max(polled_at) as ref_time from {{ ref('stg_velib__station_status') }}
),

-- alias préfixés « cur_ » : ClickHouse refuse qu'un alias masque une colonne utilisée dans un autre agrégat
latest as (
    select
        s.station_id                                       as station_id,
        argMax(s.report_lag_minutes, s.polled_at)          as cur_report_lag_minutes,
        argMax(s.last_reported, s.polled_at)               as cur_last_reported,
        argMax(s.is_installed, s.polled_at)                as cur_is_installed,
        argMax(s.is_renting, s.polled_at)                  as cur_is_renting,
        argMax(s.is_returning, s.polled_at)                as cur_is_returning,
        maxIf(s.polled_at, s.is_renting or s.is_returning) as last_open_at,
        max(s.polled_at)                                   as last_polled_at
    from {{ ref('stg_velib__station_status') }} as s
    where s.polled_at >= (select ref_time from ref) - interval 2 day
    group by s.station_id
),

stale as (
    select
        station_id,
        'STALE_DATA'                          as anomaly_type,
        'critique'                            as severity,
        cur_last_reported                     as since,
        toFloat64(cur_report_lag_minutes)     as metric_value,
        'minutes sans remontée'               as metric_label
    from latest
    where cur_is_installed and cur_report_lag_minutes > {{ var('stale_after_minutes') }}
),

closed as (
    select
        station_id,
        'OUT_OF_SERVICE'                      as anomaly_type,
        'élevée'                              as severity,
        last_open_at                          as since,
        toFloat64(dateDiff('minute', last_open_at, last_polled_at)) as metric_value,
        'minutes fermée'                      as metric_label
    from latest
    where not cur_is_renting and not cur_is_returning
      and dateDiff('minute', last_open_at, last_polled_at) >= {{ var('out_of_service_after_minutes') }}
      and station_id not in (select station_id from stale)
),

docks as (
    select
        b.station_id                          as station_id,
        'DOCKS_UNAVAILABLE'                   as anomaly_type,
        'élevée'                              as severity,
        -- début : premier quart d'heure après le dernier où la station était complète
        maxIf(b.bucket, b.avg_observed_capacity >= 0.9 * d.capacity) + interval 15 minute as since,
        round(1 - avgIf(b.avg_observed_capacity / d.capacity,
                        b.bucket >= (select ref_time from ref) - interval {{ var('docks_unavailable_window_hours') }} hour), 3)
                                              as metric_value,
        'part des bornettes indisponibles'   as metric_label
    from {{ ref('int_station_status_15min') }} as b
    inner join {{ ref('dim_station') }} as d on d.station_id = b.station_id
    where b.bucket >= (select ref_time from ref) - interval 1 day
      and d.capacity > 0
      and b.station_id not in (select station_id from stale)
    group by b.station_id
    having maxIf(b.avg_observed_capacity / d.capacity,
                 b.bucket >= (select ref_time from ref) - interval {{ var('docks_unavailable_window_hours') }} hour)
           < {{ var('docks_unavailable_ratio') }}
),

chronic as (
    select
        station_id,
        multiIf(avg(share_near_empty) > {{ var('chronic_share') }}, 'CHRONIC_EMPTY', 'CHRONIC_FULL') as anomaly_type,
        'moyenne'                             as severity,
        min(bucket)                           as since,
        round(greatest(avg(share_near_empty), avg(share_near_full)), 3) as metric_value,
        'part du temps en journée'            as metric_label
    from {{ ref('int_station_status_15min') }}
    where bucket >= (select ref_time from ref) - interval {{ var('chronic_window_hours') }} hour
      and local_hour >= {{ var('daytime_start_hour') }} and local_hour < {{ var('daytime_end_hour') }}
      and station_id not in (select station_id from stale)
    group by station_id
    having avg(share_near_empty) > {{ var('chronic_share') }} or avg(share_near_full) > {{ var('chronic_share') }}
),

unioned as (
    select * from stale
    union all select * from closed
    union all select * from docks
    union all select * from chronic
)

select
    a.station_id                              as station_id,
    d.station_code                            as station_code,
    d.station_name                            as station_name,
    d.capacity                                as capacity,
    d.lat                                     as lat,
    d.lon                                     as lon,
    a.anomaly_type                            as anomaly_type,
    a.severity                                as severity,
    a.since                                   as since,
    a.metric_value                            as metric_value,
    a.metric_label                            as metric_label,
    -- priorité : gravité × taille de la station (une grande station en panne pèse plus sur le réseau)
    multiIf(a.severity = 'critique', 3, a.severity = 'élevée', 2, 1) * d.capacity as priority_score,
    (select ref_time from ref)                as detected_at
from unioned as a
inner join {{ ref('dim_station') }} as d on d.station_id = a.station_id
