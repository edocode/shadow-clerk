YEAR := $(shell date +%Y)
AUTHOR := Atsushi Kato

.PHONY: license help

license: ## Generate LICENSE file
	@sed 's/Copyright (c) [0-9]*/Copyright (c) $(YEAR)/' LICENSE > LICENSE.tmp && mv LICENSE.tmp LICENSE
	@echo "LICENSE updated (year: $(YEAR))"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'
