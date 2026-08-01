FROM python:3.11.15-slim-bookworm

ENV HOME=/home/labelcheck \
    XDG_CACHE_HOME=/home/labelcheck/.cache \
    XDG_CONFIG_HOME=/home/labelcheck/.config \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 labelcheck \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash labelcheck \
    && install -d --owner=labelcheck --group=labelcheck \
        /app \
        /home/labelcheck/.cache \
        /home/labelcheck/.config \
        /home/labelcheck/.streamlit

WORKDIR /app

COPY requirements.txt ./
# RapidOCR also declares the GUI OpenCV distribution. Reapply the runtime-pinned
# headless wheel last so the two distributions' shared cv2 files stay headless.
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir --force-reinstall --no-deps \
        "$(sed -n '/^opencv-python-headless==/p' requirements.txt)"

COPY --chown=labelcheck:labelcheck app.py ./
COPY --chown=labelcheck:labelcheck src/ ./src/

USER labelcheck

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true"]
