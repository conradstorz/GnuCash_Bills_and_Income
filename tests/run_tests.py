#!/usr/bin/env python3
"""
Test runner for bill workflow tests
"""
import subprocess
import sys
from pathlib import Path

def run_tests():
    """Run the bill workflow tests"""
    test_dir = Path(__file__).parent
    
    print("Running Bill Workflow Tests...")
    print("=" * 50)
    
    # Run automated tests only (skip manual ones)
    result = subprocess.run([
        sys.executable, "-m", "pytest", 
        str(test_dir / "test_bill_workflow.py"),
        "-v", "-m", "not manual"
    ])
    
    if result.returncode == 0:
        print("\n✅ All automated tests passed!")
        
        # Ask if user wants to run manual tests
        response = input("\nRun manual verification tests? (y/n): ")
        if response.lower().startswith('y'):
            print("\nRunning manual tests...")
            subprocess.run([
                sys.executable, "-m", "pytest",
                str(test_dir / "test_bill_workflow.py"), 
                "-v", "-m", "manual", "-s"
            ])
    else:
        print("\n❌ Some tests failed!")
        
    return result.returncode

if __name__ == "__main__":
    sys.exit(run_tests())