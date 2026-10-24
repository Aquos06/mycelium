# laya-serve in a pinned image. The PyTorch wheels on PyPI bundle their CUDA libraries, so a plain
# Python base is enough: the GPU comes from the host driver through the NVIDIA Container Toolkit
# (docker-compose.gpu.yml). The same image runs on CPU with LAYA_DEVICE=cpu.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN useradd --create-home --uid 10001 laya && mkdir -p /models && chown laya:laya /models
USER laya
EXPOSE 8000
CMD ["laya-serve"]
