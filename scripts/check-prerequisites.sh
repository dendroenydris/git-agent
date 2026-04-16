#!/bin/bash

echo "🔍 Checking AutoDev Agent Prerequisites..."
echo "========================================="

# Check Node.js version
echo "📦 Checking Node.js version..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | sed 's/v//')
    REQUIRED_VERSION="18.17.0"
    
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$NODE_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
        echo "✅ Node.js $NODE_VERSION (>= $REQUIRED_VERSION required)"
    else
        echo "❌ Node.js $NODE_VERSION is too old. Upgrade to >= $REQUIRED_VERSION"
        echo "   Install via: https://nodejs.org/ or nvm install 18"
        exit 1
    fi
else
    echo "❌ Node.js not found. Install from https://nodejs.org/"
    exit 1
fi

# Check Python version
echo "🐍 Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo "✅ Python $PYTHON_VERSION"
else
    echo "❌ Python 3 not found. Install Python 3.10+"
    exit 1
fi

# Check for Conda (optional)
echo "🔧 Checking Conda (optional)..."
if command -v conda &> /dev/null; then
    CONDA_VERSION=$(conda --version | cut -d' ' -f2)
    echo "✅ Conda $CONDA_VERSION"
    CONDA_AVAILABLE=true
else
    echo "⚠️  Conda not found (optional). Install from https://docs.conda.io/en/latest/miniconda.html"
    CONDA_AVAILABLE=false
fi

# Check for Docker
echo "🐳 Checking Docker (for PostgreSQL and Redis)..."
if command -v docker &> /dev/null; then
    if docker ps &> /dev/null; then
        echo "✅ Docker is running"
        DOCKER_AVAILABLE=true
    else
        echo "⚠️  Docker is installed but not running. Start Docker to use Redis container."
        DOCKER_AVAILABLE=false
    fi
else
    echo "⚠️  Docker not found (optional). Install from https://docker.com/"
    DOCKER_AVAILABLE=false
fi

# Check for database/runtime infrastructure
echo "🗄️  Checking service runtime..."
if [ "$DOCKER_AVAILABLE" = true ]; then
    echo "✅ PostgreSQL and Redis can be started with Docker Compose"
else
    echo "⚠️  Docker is unavailable. You will need local PostgreSQL and Redis"
fi

# Check for Git
echo "📝 Checking Git..."
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version | cut -d' ' -f3)
    echo "✅ Git $GIT_VERSION"
else
    echo "❌ Git not found. Install Git"
    exit 1
fi

echo ""
echo "🎉 Prerequisites Check Complete!"
echo "================================="

# Provide setup recommendations
echo ""
echo "📋 Recommended Setup:"
if [ "$CONDA_AVAILABLE" = true ]; then
    echo "1. npm run conda:setup                # Create or update conda environment"
    echo "2. npm run dev:all-conda              # Start PostgreSQL, Redis, API, worker, frontend"
else
    echo "1. npm run backend:setup-pip          # Create virtual environment"
    echo "2. docker compose up -d postgres redis"
    echo "3. Run frontend, API, and worker manually"
fi

echo ""
echo "🚀 Ready to start! Create .env files with your OpenAI API key first."
echo "   Backend: backend/.env"
echo "   Frontend: .env.local" 