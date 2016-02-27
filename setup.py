from setuptools import setup
import versioneer

setup(
    name='pypeliner',
    packages=['pypeliner'],
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    description='A library for creating informatic workflows or pipelines.',
    author='Andrew McPherson',
    author_email='andrew.mcpherson@gmail.com',
    url='http://bitbucket.org/dranew/pypeliner',
    download_url='https://bitbucket.org/dranew/pypeliner/get/v0.4.1.tar.gz',
    keywords=['scientific', 'framework'],
    classifiers=[],
)

