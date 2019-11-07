import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="lumber",
    version="0.0.1",
    author="InfiniteToken",
    author_email="infinitetoken@gmail.com",
    description="A Python package for cloud logging",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/infinitetoken/Lumber-Python",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
