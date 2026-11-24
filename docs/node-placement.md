# Node placement

The production values set `nodeSelector: {rag-worker: enabled}`. Label only the general-purpose workers:

```bash
kubectl label node <worker-node> rag-worker=enabled
```

The chart does not name `ai-r113-s1`, `ai-r113-s2`, `ai-r113-s3`, or any control-plane node, and it adds no control-plane toleration. Per-component `nodeSelector` overrides the global one.
