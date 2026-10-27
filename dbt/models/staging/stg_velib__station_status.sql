-- Relevés nettoyés : noms explicites, booléens, retard de remontée de la station.
select
    station_id,
    station_code,
    polled_at,
    last_reported,
    num_bikes_available                         as bikes,
    num_mechanical                              as bikes_mechanical,
    num_ebike                                   as bikes_ebike,
    num_docks_available                         as docks,
    num_bikes_available + num_docks_available   as observed_capacity,
    is_installed = 1                            as is_installed,
    is_renting = 1                              as is_renting,
    is_returning = 1                            as is_returning,
    greatest(dateDiff('minute', last_reported, polled_at), 0) as report_lag_minutes
from {{ source('velib', 'station_status') }}
-- un même relevé peut arriver deux fois (rejeu Kafka) : on n'en garde qu'un
order by station_id, polled_at
limit 1 by station_id, polled_at
