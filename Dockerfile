# Use an official Python runtime as a parent image
FROM python:3.11

# Set the working directory
WORKDIR /app

# Copy your application code
COPY . .

# Install dependencies
RUN pip install -r requirements.txt

# Make the startup script executable
RUN chmod +x start.sh

# Run the startup script
CMD ["./start.sh"]
