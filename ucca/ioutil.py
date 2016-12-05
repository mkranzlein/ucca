"""Utility functions for UCCA scripts."""
import os
import pickle
import sys
import time
from xml.etree.ElementTree import ElementTree, tostring
from xml.etree.ElementTree import ParseError

from parsing.config import Config
from ucca.convert import from_standard, to_standard, FROM_FORMAT, TO_FORMAT, from_text, split2segments
from ucca.core import Passage
from ucca.textutil import indent_xml


def file2passage(filename):
    """Opens a file and returns its parsed Passage object
    Tries to read both as a standard XML file and as a binary pickle
    :param filename: file name to write to
    """
    try:
        with open(filename) as f:
            etree = ElementTree().parse(f)
        return from_standard(etree)
    except Exception as e:
        try:
            with open(filename, 'rb') as h:
                return pickle.load(h)
        except Exception:
            raise e


def passage2file(passage, filename, indent=True, binary=False):
    """Writes a UCCA passage as a standard XML file or a binary pickle
    :param passage: passage object to write
    :param filename: file name to write to
    :param indent: whether to indent each line
    :param binary: whether to write pickle format (or XML)
    """
    if binary:
        with open(filename, 'wb') as h:
            pickle.dump(passage, h)
    else:  # xml
        root = to_standard(passage)
        xml = tostring(root).decode()
        output = indent_xml(xml) if indent else xml
        with open(filename, 'w') as h:
            h.write(output)


class LazyLoadedPassages(object):
    """
    Iterable interface to Passage objects that loads files on-the-go and can be iterated more than once
    """
    def __init__(self, files):
        self.files = files
        self._files_iter = None
        self._split_iter = None
        self._file_handle = None
        self._len = None
        self._next_index = None

    def __iter__(self):
        self._next_index = 0
        self._files_iter = iter(self.files)
        self._split_iter = None
        self._file_handle = None
        return self

    def __next__(self):
        passage = self._next_passage()
        self._next_index += 1
        return passage

    def _next_passage(self):
        passage = None
        if self._split_iter is None:
            try:
                file = next(self._files_iter)
            except StopIteration:  # Finished iteration
                if self._len is None:
                    self._len = self._next_index
                else:
                    assert self._len == self._next_index, "Number of elements changed between iterations: %d != %d" % (
                        self._len, self._next_index)
                raise StopIteration
            if isinstance(file, Passage):  # Not really a file, but a Passage
                passage = file
            elif os.path.exists(file):  # A file
                try:
                    passage = file2passage(file)  # XML or binary format
                except (IOError, ParseError):  # Failed to read as passage file
                    base, ext = os.path.splitext(os.path.basename(file))
                    converter = FROM_FORMAT.get(ext.lstrip("."), from_text)
                    self._file_handle = open(file)
                    self._split_iter = iter(converter(self._file_handle, passage_id=base, split=Config().split))
            else:
                print("File not found: %s" % file, file=sys.stderr)
                time.sleep(1)
                return next(self)
            if Config().split and self._split_iter is None:  # If it's not None, it's a converter and it splits alone
                self._split_iter = iter(split2segments(passage, is_sentences=Config().args.sentences))
        if self._split_iter is not None:  # Either set before or initialized now
            try:
                passage = next(self._split_iter)
            except StopIteration:  # Finished this converter
                self._split_iter = None
                if self._file_handle is not None:
                    self._file_handle.close()
                    self._file_handle = None
                return next(self)
        return passage

    def __len__(self):
        if self._len is None:
            raise ValueError("Must finish first iteration to get len")
        return self._len

    def __bool__(self):
        return bool(self.files)

    def shuffle(self):
        Config().random.shuffle(self.files)  # Does not shuffle within a file - might be a problem


def read_files_and_dirs(files_and_dirs):
    """
    :param files_and_dirs: iterable of files and/or directories to look in
    :return: list of (lazy-loaded) passages from all files given,
             plus any files directly under any directory given
    """
    files = list(files_and_dirs)
    files += [os.path.join(d, f) for d in files if os.path.isdir(d) for f in os.listdir(d)]
    files = [f for f in files if not os.path.isdir(f)]
    return LazyLoadedPassages(files)


def write_passage(passage, args):
    suffix = args.format or ("pickle" if args.binary else "xml")
    outfile = args.outdir + os.path.sep + args.prefix + passage.ID + "." + suffix
    print("Writing passage '%s'..." % outfile)
    if args.format is None:
        passage2file(passage, outfile, binary=args.binary)
    else:
        converter = TO_FORMAT[args.format]
        output = "\n".join(line for line in converter(passage))
        with open(outfile, "w") as f:
            f.write(output + "\n")
