from setuptools import setup, find_packages

setup(
    name='ishu',
    version='1.0',
    url='https://github.com/nycz/ishu',
    author='nycz',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'ishu=ishu.ishu:main'
        ]
    }
)
