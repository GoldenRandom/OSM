FROM python:3.10-slim

# Install necessary packages for Playwright and Xvfb (Virtual Display)
RUN apt-get update && apt-get install -y \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries and OS dependencies
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# Run the script using xvfb (virtual display) so headless=False works
CMD ["xvfb-run", "--auto-servernum", "--server-args='-screen 0 1280x800x24'", "python", "-u", "claimer.py"]
