YEAR := $(shell date +%Y)
AUTHOR := Atsushi Kato

.PHONY: license dupcheck mypy help slides slides-pdf build clean-dist publish publish-test

license: ## Generate LICENSE file
	@sed 's/Copyright (c) [0-9]*/Copyright (c) $(YEAR)/' LICENSE > LICENSE.tmp && mv LICENSE.tmp LICENSE
	@echo "LICENSE updated (year: $(YEAR))"

dupcheck: ## Check duplicate code (pylint R0801)
	uv run pylint --disable=all --enable=R0801 src/shadow_clerk/

mypy: ## Type check with mypy
	uv run mypy src/shadow_clerk/

slides: ## Build HTML slides from docs/slides.md (renders Mermaid via mmdc)
	npx -y -p @mermaid-js/mermaid-cli mmdc -p docs/.puppeteer-config.json -i docs/slides.md -o docs/slides.rendered.md
	npx -y @marp-team/marp-cli docs/slides.rendered.md -o docs/slides.html --allow-local-files
	@echo "→ docs/slides.html"

slides-pdf: ## Build PDF slides from docs/slides.md (renders Mermaid via mmdc)
	npx -y -p @mermaid-js/mermaid-cli mmdc -p docs/.puppeteer-config.json -i docs/slides.md -o docs/slides.rendered.md
	npx -y @marp-team/marp-cli docs/slides.rendered.md --pdf -o docs/slides.pdf --allow-local-files
	@echo "→ docs/slides.pdf"

clean-dist: ## Remove dist/ build artifacts
	rm -rf dist/

build: clean-dist ## Build sdist + wheel into dist/
	uv build
	uv run --with twine twine check dist/*

publish-test: build ## Upload to TestPyPI (requires [testpypi] in ~/.pypirc)
	uv run --with twine twine upload --repository testpypi dist/*

publish: build ## Upload to PyPI (requires [pypi] in ~/.pypirc)
	uv run --with twine twine upload dist/*

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'
