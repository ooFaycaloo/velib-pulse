-- Référentiel enrichi : capacité, position et comportement moyen sur les 7 derniers jours.
with stats as (
    select
        station_id,
        avg(avg_bikes)                                         as avg_bikes_7d,
        avgIf(avg_bikes, local_hour between 7 and 10)          as avg_bikes_morning,
        avgIf(avg_bikes, local_hour between 17 and 20)         as avg_bikes_evening,
        avg(share_empty)                                       as share_empty_7d,
        avg(share_full)                                        as share_full_7d
    from {{ ref('int_station_status_15min') }}
    where bucket >= (select max(bucket) from {{ ref('int_station_status_15min') }}) - interval 7 day
    group by station_id
)
select
    i.station_id                                               as station_id,
    i.station_code                                             as station_code,
    i.station_name                                             as station_name,
    i.lat                                                      as lat,
    i.lon                                                      as lon,
    i.capacity                                                 as capacity,
    s.avg_bikes_7d                                             as avg_bikes_7d,
    s.avg_bikes_7d / nullIf(i.capacity, 0)                     as avg_occupancy_7d,
    s.share_empty_7d                                           as share_empty_7d,
    s.share_full_7d                                            as share_full_7d,
    -- profil d'usage : la station se vide le matin (résidentielle) ou se remplit (pôle d'emploi)
    multiIf(
        s.avg_bikes_morning < 0.7 * s.avg_bikes_evening, 'résidentielle',
        s.avg_bikes_morning > 1.3 * s.avg_bikes_evening, 'bureaux',
        'mixte'
    )                                                          as usage_profile
from {{ ref('stg_velib__station_information') }} as i
left join stats as s on s.station_id = i.station_id
