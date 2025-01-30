from setuptools import setup, find_packages

setup(
    name="lss-training-assistant",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        'fastapi',
        'uvicorn',
        'pandas',
        'google-auth-oauthlib',
        'google-auth-httplib2',
        'google-api-python-client',
        'openai',
        'python-dotenv',
        'tenacity',
        'ratelimit',
        'prometheus-client'
    ]
) 