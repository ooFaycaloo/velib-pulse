# Raccourcis. Mode « dev » : ClickHouse embarqué (chDB), sans Docker.
PORT ?= 8123
export CLICKHOUSE_PORT ?= $(PORT)
export DBT_PROFILES_DIR := $(CURDIR)/dbt

.PHONY: dev-server demo dbt report brief eval test up live mcp

dev-server:          ## ClickHouse embarqué compatible HTTP sur :$(PORT)
	TZ=UTC python devtools/chdb_http_server.py --path .chdb --port $(PORT)

demo:                ## 48 h simulées → ClickHouse → dbt → rapport HTML
	python -m velib_pulse.producer --source simulate --sink clickhouse --backfill-hours 48 --once
	$(MAKE) dbt
	python -m velib_pulse.report --simulated --out reports/velib_pulse.html

dbt:
	cd dbt && dbt build

report:
	python -m velib_pulse.report --out reports/velib_pulse.html

brief:
	python -m velib_pulse.agent

eval:                ## détection d'incidents sur 5 simulations
	python eval/evaluate.py --seeds 1 2 3 4 5

test:
	python -m pytest -q

up:                  ## pile complète Docker (Redpanda, ClickHouse, producteur sur le flux réel)
	docker compose up -d --build

live:                ## producteur flux réel → Kafka, depuis l'hôte
	python -m velib_pulse.producer --source live --sink kafka --interval 60

mcp:
	python -m velib_pulse.mcp_server
