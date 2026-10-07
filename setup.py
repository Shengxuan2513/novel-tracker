from setuptools import setup, find_packages
from pathlib import Path

with (Path(__file__).parent / "README.md").open("r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="novel-tracker",
    version="2.0.0",
    author="NovelTracker Contributors",
    description="基于“主索引探针 + 多源降级回源”的分布式小说聚合监控与通用提取系统",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Shengxuan2513/novel-tracker",
    packages=find_packages(exclude=["tests", "tests.*"]),
    py_modules=["cli"],
    package_data={"sources": ["rules/*.json"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.14",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "httpx>=0.24.0",
        "aiohttp>=3.8.0",
        "beautifulsoup4>=4.11.0",
        "lxml>=4.9.0",
        "trafilatura>=1.6.0",
        "ebooklib>=0.20",
        "psutil>=5.9",
    ],
    extras_require={"test": ["pytest>=7"]},
    entry_points={
        "console_scripts": [
            "novel-tracker=cli:main",
        ],
    },
)
