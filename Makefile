PYTHON ?= python3

.DEFAULT_GOAL := help

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install Python dependencies
	$(PYTHON) -m pip install -r requirements.txt

run: ## Run the Flask app locally on port 5000
	$(PYTHON) app.py

test: ## Run the unit tests
	$(PYTHON) -m unittest discover -s tests -v

export-crm: ## Export saved deals as CRM JSON payloads to crm_export.json
	$(PYTHON) export_deals.py --out crm_export.json

.PHONY: help install run test export-crm
