-- Santé du réseau par quart d'heure : vélos disponibles, stations vides / pleines / muettes.
select
    b.bucket                                                        as bucket,
    count()                                                         as stations_reporting,
    round(sum(b.avg_bikes))                                         as bikes_available,
    round(sum(b.avg_bikes_ebike))                                   as ebikes_available,
    round(sum(b.avg_docks))                                         as docks_available,
    countIf(b.avg_bikes < 1)                                        as stations_empty,
    countIf(b.avg_docks < 1)                                        as stations_full,
    countIf(b.max_report_lag_minutes > {{ var('stale_after_minutes') }}) as stations_stale,
    countIf(b.share_closed > 0.5)                                   as stations_closed,
    countIf(b.avg_observed_capacity < {{ var('docks_unavailable_ratio') }} * d.capacity)  as stations_docks_degraded,
    countIf(b.max_report_lag_minutes > {{ var('stale_after_minutes') }}
            or b.share_closed > 0.5
            or b.avg_observed_capacity < {{ var('docks_unavailable_ratio') }} * d.capacity) as stations_faulty,
    round(countIf(b.avg_bikes >= 1 and b.avg_docks >= 1) / count(), 4)  as share_stations_usable
from {{ ref('int_station_status_15min') }} as b
inner join {{ ref('dim_station') }} as d on d.station_id = b.station_id
group by b.bucket
