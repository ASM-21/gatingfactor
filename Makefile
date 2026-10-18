.PHONY: help test claims verify queue hosting carbon tariff dashboard report clean

help:
	@echo "make test       run the full test suite (155 tests)"
	@echo "make claims     verify every quoted figure recomputes from results"
	@echo "make verify     test + claims, what CI runs"
	@echo "make report     regenerate every figure and table"
	@echo "make queue      regenerate interconnection-analytics"
	@echo "make hosting    regenerate hosting-capacity-sim"
	@echo "make tariff     regenerate tariff-explorer"
	@echo "make carbon     regenerate carbon-aware-der"
	@echo "make dashboard  launch the tariff-explorer Streamlit app"

test:
	python -m pytest tests/ -q

claims:
	python tools/check_claims.py

verify: test claims

queue:
	cd interconnection-analytics && python run_analysis.py

hosting:
	cd hosting-capacity-sim && python run_analysis.py

tariff:
	cd tariff-explorer && python run_analysis.py

carbon:
	cd carbon-aware-der && python run_analysis.py

report: queue hosting tariff carbon

dashboard:
	cd tariff-explorer && streamlit run app.py

clean:
	rm -rf data/processed outputs
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
