"""
Centralized logging setup for the Bill Processor application.

Import and call setup_logging() early in each entry point script.
All other modules should just import logger from loguru.
"""

import sys
from pathlib import Path
from loguru import logger
from bill_processor import config


def setup_logging(
    log_level: str = None,
    console_level: str = None,
    file_level: str = None,
    log_file: Path = None,
    module_name: str = None
) -> None:
    """
    Configure loguru logging for the application.
    
    Args:
        log_level: Overall log level (DEBUG, INFO, WARNING, ERROR)
        console_level: Console-specific log level (overrides log_level if set)
        file_level: File-specific log level (overrides log_level if set)  
        log_file: Path to log file (uses config default if None)
        module_name: Name of module setting up logging (for log messages)
    """
    # Use config defaults if not specified
    if log_level is None:
        log_level = getattr(config, 'LOG_LEVEL', 'INFO')
    if console_level is None:
        console_level = 'INFO'  # Always INFO for console to avoid debug spam
    if file_level is None:
        file_level = 'DEBUG'  # Always debug to file
    if log_file is None:
        log_file = getattr(config, 'LOG_FILE_PATH', None)
    
    # Remove any existing handlers
    logger.remove()
    
    # Console handler - colored output with clean format
    logger.add(
        sys.stderr,
        level=console_level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True
    )
    
    # File handler - detailed format with rotation
    if log_file:
        # Ensure log directory exists
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            log_file,
            level=file_level.upper(),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="5 MB",  # Rotate when file gets to 5MB
            retention="30 days",  # Keep logs for 30 days
            compression="zip",  # Compress old logs
            backtrace=True,  # Include full stack traces
            diagnose=True  # Include variable values in stack traces
        )
        
        # Log that we set up logging
        if module_name:
            logger.info(f"Logging initialized by {module_name} - Level: {console_level}, File: {log_file}")
        else:
            logger.info(f"Logging initialized - Level: {console_level}, File: {log_file}")
    else:
        # Log that file logging is disabled
        if module_name:
            logger.info(f"Logging initialized by {module_name} - Level: {console_level}, File logging disabled")
        else:
            logger.info(f"Logging initialized - Level: {console_level}, File logging disabled")


def setup_logging_for_script(script_name: str) -> None:
    """
    Convenience function to set up logging for a specific script.
    Uses the script name for context and applies standard settings.
    """
    setup_logging(module_name=script_name)
    logger.debug(f"Starting {script_name}")


def log_function_entry(func_name: str, **kwargs) -> None:
    """Helper to log function entry with parameters."""
    if kwargs:
        params = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        logger.debug(f"→ {func_name}({params})")
    else:
        logger.debug(f"→ {func_name}()")


def log_function_exit(func_name: str, result=None) -> None:
    """Helper to log function exit with optional return value."""
    if result is not None:
        logger.debug(f"← {func_name}() → {result}")
    else:
        logger.debug(f"← {func_name}()")


def log_database_operation(operation: str, table: str, **details) -> None:
    """Helper to log database operations consistently."""
    if details:
        detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
        logger.debug(f"DB: {operation} {table} ({detail_str})")
    else:
        logger.debug(f"DB: {operation} {table}")


def log_api_call(service: str, endpoint: str, **details) -> None:
    """Helper to log API calls consistently."""
    if details:
        detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
        logger.debug(f"API: {service} {endpoint} ({detail_str})")
    else:
        logger.debug(f"API: {service} {endpoint}")


def log_stage(stage_name: str) -> None:
    """Helper to log major stages/phases of operation."""
    logger.info(f"=== {stage_name} ===")


def log_error_with_context(error: Exception, context: str = None, **kwargs) -> None:
    """Helper to log errors with full context."""
    if context:
        logger.error(f"{context}: {type(error).__name__}: {error}")
    else:
        logger.error(f"{type(error).__name__}: {error}")
    
    if kwargs:
        for key, value in kwargs.items():
            logger.error(f"  {key}: {value}")


# Backwards compatibility aliases
def configure_logging(*args, **kwargs):
    """Alias for setup_logging() for backwards compatibility."""
    return setup_logging(*args, **kwargs)