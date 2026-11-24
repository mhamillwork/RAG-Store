# Images

Build from the repository root:

```bash
docker build -f dockerfile/Dockerfile.rag-store-api -t rag-store-api:1.0.0 .
```

`scripts/build-images.sh` builds all seven images. `scripts/push-images.sh` requires `REGISTRY`; it does not assume a host.

The GUI image builds the React application and serves it with the unprivileged nginx image. The Docling image installs `docling==2.152.0`, Tesseract, and CPU libraries. It sets the Hugging Face offline variables.

Images were not built in the development environment used to write this repository.
