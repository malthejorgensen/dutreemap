dutreemap
===========
`dutreemap` is a mini-app that shows your disk use in a "tree map" which is a
good visualization of what takes up space on your disk.

Internals
---------
It's Python script that opens a Tk window and uses Tk widgets to display the
map.

Prior art
---------
In general, there's a lot :)

I took my inspiration from [Disk Inventoty X] ([gitlab repo]), which I've been
a fan of (and used) for many years but it's no longer installable using [Homebrew]
so I decided to just have Claude code up something for me.

For Python specifically there's [python-du] which looks pretty cool. Found it
after I implemented this version.

[Disk Inventory X]: https://www.derlien.com/
[gitlab repo]: https://gitlab.com/tderlien/disk-inventory-x
[python-du]: https://pypi.org/project/python-du/
[Homebrew]: https://brew.sh
