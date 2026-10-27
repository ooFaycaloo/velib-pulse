{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='bucket',
        engine='MergeTree()',
        order_by='(station_id, bucket)',
        partition_by='toYYYYMMDD(bucket)'
    )
}}
-- Agrégat par station et par quart d'heure : la granularité de travail de tous les marts.
-- Incrémental : à chaque exécution, seuls les quarts d'heure récents sont recalculés.
select
    station_id,
    toStartOfFifteenMinutes(polled_at)                        as bucket,
    toHour(toTimeZone(toStartOfFifteenMinutes(polled_at), 'Europe/Paris')) as local_hour,
    count()                                                   as n_polls,
    avg(bikes)                                                as avg_bikes,
    min(bikes)                                                as min_bikes,
    max(bikes)                                                as max_bikes,
    avg(bikes_ebike)                                          as avg_bikes_ebike,
    avg(docks)                                                as avg_docks,
    avg(observed_capacity)                                    as avg_observed_capacity,
    countIf(bikes = 0) / count()                              as share_empty,
    countIf(docks = 0) / count()                              as share_full,
    -- « quasi vide / quasi pleine » : 0 ou 1 vélo (resp. place) restant, inutilisable en pratique
    countIf(bikes < {{ var('near_threshold') }}) / count()    as share_near_empty,
    countIf(docks < {{ var('near_threshold') }}) / count()    as share_near_full,
    max(report_lag_minutes)                                   as max_report_lag_minutes,
    countIf(not is_renting and not is_returning) / count()    as share_closed
from {{ ref('stg_velib__station_status') }}
{% if is_incremental() %}
where polled_at >= (select max(bucket) - interval 1 hour from {{ this }})
{% endif %}
group by station_id, bucket
