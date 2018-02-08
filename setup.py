# Copyright (c) 2017 David Preece - davep@polymath.tech, All rights reserved.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.


from setuptools import setup

setup(
    name='messidge',
    version='1.1.4',
    author='David Preece',
    author_email='davep@20ft.nz',
    url='https://20ft.nz',
    license='BSD',
    packages=['messidge', 'messidge.broker', 'messidge.client'],
    install_requires=['pyzmq', 'libnacl', 'shortuuid', 'psutil', 'lru-dict', 'cbor', 'bottle', 'litecache'],
    description='A message passing library for gateways onto the public Internet.',
    long_description="There are some users, and some nodes (on a private LAN). Messidge brokers between the two. "
                     "It authenticates, encrypts, and can validate the provenance of an rpc call.",
    keywords='message messages message-passing authenticated encrypted gateway',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Framework :: Bottle',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: BSD License',
        'Topic :: Security',
        'Topic :: Security :: Cryptography',
        'Topic :: Software Development :: Object Brokering',
        'Topic :: System :: Distributed Computing',
        'Topic :: System :: Networking',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6'
    ]
)
