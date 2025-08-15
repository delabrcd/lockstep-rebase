#!/bin/bash
# Setup script for Git Submodule Rebase Tool on Linux

echo "🚀 Setting up Git Submodule Rebase Tool on Linux..."

# Navigate to project directory
cd ~/dev/misc/git-submodule-rebase-tool

# Create virtual environment
echo "📦 Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install the project in development mode
echo "🔧 Installing project dependencies..."
pip install -e ".[dev]"

# Run tests to verify installation
echo "🧪 Running tests to verify installation..."
pytest tests/ -v

# Make the CLI command available globally (optional)
echo "🔗 Setting up global CLI access..."
echo 'export PATH="$HOME/dev/misc/git-submodule-rebase-tool/venv/bin:$PATH"' >> ~/.bashrc

# Create test repository for demonstration
echo "🏗️  Setting up test repository..."
python3 setup_test_repo.py

echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Source your bashrc: source ~/.bashrc"
echo "2. Test the CLI: git-submodule-rebase --help"
echo "3. Try the test repo: cd nested-git-playground/main-repo"
echo "4. Run: git-submodule-rebase status"
echo ""
echo "🎉 Your Git Submodule Rebase Tool is ready to use!"
