# Step 58 diagrams

- `system_architecture.svg` / `system_architecture.dot` — architecture of deployed application and processing infrastructure
- `agent_loop.svg` / `agent_loop.dot` — bounded perception/decision/action workflow, not unbounded autonomous agency

Regenerate SVGs with Graphviz (optional):

```bash
dot -Tsvg docs/step58/system_architecture.dot -o docs/step58/system_architecture.svg
dot -Tsvg docs/step58/agent_loop.dot -o docs/step58/agent_loop.svg
```

The SVGs are self-contained vector diagrams. The DOT sources are the editable originals. Use `STEP58_EVIDENCE.md` for provenance and important limitations. Avoid including private inspection IDs or direct presigned video links in published illustrations.
