# Python 3.13: Feature Summary

> **Release Date:** October 7, 2024  
> **Release Notes:** [Python 3.13.0 Release Notes](https://www.python.org/downloads/release/python-3130/)  
> **Full Documentation:** [What’s New in Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)

---

## 📌 Table of Contents
1. [New Syntax and Language Features](#1-new-syntax-and-language-features)
2. [Performance Improvements](#2-performance-improvements)
3. [Standard Library Updates](#3-standard-library-updates)
4. [Deprecations and Removals](#4-deprecations-and-removals)
5. [Tooling and Developer Experience](#5-tooling-and-developer-experience)
6. [Other Significant Changes](#6-other-significant-changes)
7. [Summary Table of Key Changes](#summary-table-of-key-changes)
8. [References](#references)

---

## 1. New Syntax and Language Features

### 🔹 Type Parameter Defaults (PEP 696)
- Type parameters (`TypeVar`, `ParamSpec`, `TypeVarTuple`) now support default values.
- Example:
  ```python
  from typing import TypeVar
  T = TypeVar("T", default=int)
  ```
- **Reference:** [PEP 696](https://peps.python.org/pep-0696/)

### 🔹 `typing.TypeIs` for Type Narrowing (PEP 742)
- Introduced `TypeIs` as a more intuitive alternative to `TypeGuard` for type narrowing.
- Example:
  ```python
  from typing import TypeIs
  def is_str(obj: object) -> TypeIs[str]:
      return isinstance(obj, str)
  ```
- **Reference:** [PEP 742](https://peps.python.org/pep-0742/)

### 🔹 `typing.ReadOnly` for TypedDict (PEP 705)
- Allows marking items in a `TypedDict` as read-only for type checkers.
- Example:
  ```python
  from typing import TypedDict, ReadOnly
  class Config(TypedDict):
      name: str
      version: ReadOnly[int]
  ```
- **Reference:** [PEP 705](https://peps.python.org/pep-0705/)

### 🔹 `warnings.deprecated()` Decorator (PEP 702)
- Adds support for marking deprecations in the type system and at runtime.
- Example:
  ```python
  from warnings import deprecated
  @deprecated("Use 'new_function' instead.")
  def old_function():
      pass
  ```
- **Reference:** [PEP 702](https://peps.python.org/pep-0702/)

### 🔹 Docstring Indentation Stripping
- Leading indentation is now stripped from docstrings, reducing memory usage and `.pyc` file size.

---

## 2. Performance Improvements

### 🚀 Experimental Just-In-Time (JIT) Compiler (PEP 744)
- Python 3.13 includes a **basic JIT compiler** (disabled by default).
- Expected to improve performance in future releases.
- **Status:** Experimental, not enabled by default.
- **Reference:** [PEP 744](https://peps.python.org/pep-0744/)

### 🔓 Free-Threaded CPython (PEP 703)
- **Experimental support for disabling the Global Interpreter Lock (GIL).**
- Allows threads to run more concurrently.
- **Build Mode:** Available in Windows and macOS installers.
- **Reference:** [PEP 703](https://peps.python.org/pep-0703/)

### 📊 Improved `locals()` Semantics (PEP 667)
- `locals()` now has **well-defined semantics** when mutating the returned mapping.
- Enables debuggers and tools to update local variables more reliably, even during concurrent execution.
- **Reference:** [PEP 667](https://peps.python.org/pep-0667/)

### 💾 Modified `mimalloc` Memory Allocator
- Optional but enabled by default if supported by the platform.
- Required for free-threaded build mode.
- **Reference:** [mimalloc](https://github.com/microsoft/mimalloc)

---

## 3. Standard Library Updates

### 🆕 New Modules and Features

| Module | New Feature | Description |
|--------|-------------|-------------|
| `argparse` | Deprecation Support | Added support for deprecating command-line options, positional arguments, and subcommands. |
| `base64` | `z85encode()` and `z85decode()` | Added support for **Z85 (ZeroMQ Base85 Encoding)**. |
| `copy` | `copy.replace()` | New function to support copying with replacement for built-in types and classes defining `__replace__`. |
| `dbm` | `dbm.sqlite3` Backend | The default backend for new `dbm` files. |
| `os` | Linux Timer Notification File Descriptors | New functions for working with Linux timer notification file descriptors. |
| `random` | Command-Line Interface | Added a CLI for the `random` module. |

### ❌ Removals (PEP 594)
- **19 legacy modules** removed:
  `aifc`, `audioop`, `chunk`, `cgi`, `cgitb`, `crypt`, `imghdr`, `mailcap`, `msilib`, `nis`, `nntplib`, `ossaudiodev`, `pipes`, `sndhdr`, `spwd`, `sunau`, `telnetlib`, `uu`, `xdrlib`.
- **`lib2to3` and `2to3` tool removed** (deprecated in Python 3.11).
- **`tkinter.tix` removed** (deprecated in Python 3.6).
- **`locale.resetlocale()` removed.**
- **`typing.io` and `typing.re` namespaces removed.**

---

## 4. Deprecations and Removals

### ⚠️ New Deprecations
- Many functions, classes, and modules are now deprecated and scheduled for removal in **Python 3.15 or 3.16**.
- Example: `locale.resetlocale()`, `tkinter.tix`.

### 🗑️ Important Removals

| Module/Tool | Removal Reason |
|-------------|----------------|
| `lib2to3` | Deprecated in Python 3.11. |
| `2to3` | Deprecated in Python 3.11. |
| `tkinter.tix` | Deprecated in Python 3.6. |
| Legacy `dbm` backends | Replaced by `dbm.sqlite3`. |

---

## 5. Tooling and Developer Experience Improvements

### 💻 New Interactive Interpreter
- Based on **PyPy’s interpreter**. Features:
  - Multiline editing with history preservation.
  - Colorized prompts, tracebacks, and exceptions.
  - Direct support for REPL commands (`help`, `exit`, `quit`).
  - F1 for interactive help browsing.
  - F2 for history browsing (skips output and prompts).
  - F3 for "paste mode" for easier pasting of large code blocks.
- **Disable:** Set `PYTHON_BASIC_REPL` environment variable.
- **Reference:** [Interactive Mode Documentation](https://docs.python.org/3/tutorial/interpreter.html#tut-interactive)

### 🎨 Improved Error Messages
- **Colorized tracebacks** by default (can be disabled via `PYTHON_COLORS`, `NO_COLOR`, or `FORCE_COLOR`).
- More helpful error messages when a script has the same name as a standard library or third-party module.

### 📱 Platform Support

| Platform | Support Tier | Notes |
|----------|-------------|-------|
| **iOS** | Tier 3 | Officially supported. |
| **Android** | Tier 3 | Officially supported. |
| **WASI (WebAssembly)** | Tier 2 | Supported. |
| **Emscripten** | No longer supported | Removed as an officially supported platform. |

---

## 6. Other Significant Changes

### 🍎 Minimum macOS Version Raised
- Raised from **10.9 to 10.13 (High Sierra)**.

### 🔧 C API Improvements
- **`Py_mod_gil` slot:** Indicates if an extension module supports running with the GIL disabled.
- **`PyTime` C API:** Provides access to system clocks.
- **`PyMutex`:** New lightweight mutex (1 byte).
- **PEP 669 Monitoring Events:** New suite of functions for generating monitoring events in the C API.

---

## Summary Table of Key Changes

| Category | Feature | Status |
|----------|---------|--------|
| **Syntax** | Type parameter defaults | New |
| **Syntax** | `typing.TypeIs` | New |
| **Syntax** | `typing.ReadOnly` | New |
| **Syntax** | `warnings.deprecated()` | New |
| **Performance** | JIT Compiler (PEP 744) | Experimental |
| **Performance** | Free-Threaded CPython (PEP 703) | Experimental |
| **Performance** | Improved `locals()` semantics (PEP 667) | Stable |
| **Library** | `argparse` deprecation support | New |
| **Library** | `base64.z85encode()`/`z85decode()` | New |
| **Library** | `copy.replace()` | New |
| **Library** | `dbm.sqlite3` backend | New default |
| **Library** | `os` timer notification functions | New |
| **Library** | `random` CLI | New |
| **Removals** | 19 legacy modules (PEP 594) | Removed |
| **Removals** | `lib2to3`, `2to3`, `tkinter.tix` | Removed |
| **Tooling** | New interactive interpreter | Stable |
| **Tooling** | Colorized tracebacks | Stable |
| **Platform** | iOS/Android support | New |
| **C API** | `Py_mod_gil`, `PyTime`, `PyMutex` | New |

---

## References
1. [Python 3.13 Release Notes](https://www.python.org/downloads/release/python-3130/)
2. [What’s New in Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)
3. [PEP 696 – Type Parameter Defaults](https://peps.python.org/pep-0696/)
4. [PEP 742 – `typing.TypeIs`](https://peps.python.org/pep-0742/)
5. [PEP 705 – `typing.ReadOnly`](https://peps.python.org/pep-0705/)
6. [PEP 702 – `warnings.deprecated()`](https://peps.python.org/pep-0702/)
7. [PEP 744 – JIT Compiler](https://peps.python.org/pep-0744/)
8. [PEP 703 – Free-Threaded CPython](https://peps.python.org/pep-0703/)
9. [PEP 667 – `locals()` Semantics](https://peps.python.org/pep-0667/)
10. [PEP 594 – Removing Dead Batteries](https://peps.python.org/pep-0594/)