# Use Python 3.10 as the base image
FROM python:3.12-slim

# Set working directory in the container
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY main.py ./

# Run the application
CMD ["python", "main.py"] 
