import sys
from fontTools.ttLib.standardGlyphOrder import standardGlyphOrder
import DefaultTable
import struct, sstruct
import array
from fontTools import ttLib
from fontTools.misc.textTools import safeEval, readHex
from types import TupleType


postFormat = """
	>
	formatType:			16.16F
	italicAngle:		16.16F		# italic angle in degrees			
	underlinePosition:	h
	underlineThickness:	h
	isFixedPitch:		L
	minMemType42:		L			# minimum memory if TrueType font is downloaded
	maxMemType42:		L			# maximum memory if TrueType font is downloaded
	minMemType1:		L			# minimum memory if Type1 font is downloaded
	maxMemType1:		L			# maximum memory if Type1 font is downloaded
"""

postFormatSize = sstruct.calcsize(postFormat)


class table__p_o_s_t(DefaultTable.DefaultTable):
	
	def decompile(self, data, ttFont):
		sstruct.unpack(postFormat, data[:postFormatSize], self)
		data = data[postFormatSize:]
		if self.formatType == 1.0:
			self.decode_format_1_0(data, ttFont)
		elif self.formatType == 2.0:
			self.decode_format_2_0(data, ttFont)
		elif self.formatType == 3.0:
			self.decode_format_3_0(data, ttFont)
		else:
			# supported format
			raise ttLib.TTLibError, "'post' table format %f not supported" % self.formatType
	
	def compile(self, ttFont):
		data = sstruct.pack(postFormat, self)
		if self.formatType == 1.0:
			pass # we're done
		elif self.formatType == 2.0:
			data = data + self.encode_format_2_0(ttFont)
		elif self.formatType == 3.0:
			pass # we're done
		else:
			# supported format
			raise ttLib.TTLibError, "'post' table format %f not supported" % self.formatType
		return data
	
	def getGlyphOrder(self):
		"""This function will get called by a ttLib.TTFont instance.
		Do not call this function yourself, use TTFont().getGlyphOrder()
		or its relatives instead!
		"""
		if not hasattr(self, "glyphOrder"):
			raise ttLib.TTLibError, "illegal use of getGlyphOrder()"
		glyphOrder = self.glyphOrder
		del self.glyphOrder
		return glyphOrder
	
	def decode_format_1_0(self, data, ttFont):
		self.glyphOrder = standardGlyphOrder[:ttFont["maxp"].numGlyphs]
	
	def decode_format_2_0(self, data, ttFont):
		numGlyphs, = struct.unpack(">H", data[:2])
		numGlyphs = int(numGlyphs)
		if numGlyphs > ttFont['maxp'].numGlyphs:
			# Assume the numGlyphs field is bogus, so sync with maxp.
			# I've seen this in one font, and if the assumption is
			# wrong elsewhere, well, so be it: it's hard enough to
			# work around _one_ non-conforming post format...
			numGlyphs = ttFont['maxp'].numGlyphs
		data = data[2:]
		indices = array.array("H")
		indices.fromstring(data[:2*numGlyphs])
		if sys.byteorder <> "big":
			indices.byteswap()
		data = data[2*numGlyphs:]
		self.extraNames = extraNames = unpackPStrings(data)
		self.glyphOrder = glyphOrder = [None] * int(ttFont['maxp'].numGlyphs)
		for glyphID in range(numGlyphs):
			index = indices[glyphID]
			if index > 257:
				name = extraNames[index-258]
			else:
				# fetch names from standard list
				name = standardGlyphOrder[index]
			glyphOrder[glyphID] = name
		#AL990511: code added to handle the case of new glyphs without
		#          entries into the 'post' table
		if numGlyphs < ttFont['maxp'].numGlyphs:
			for i in range(numGlyphs, ttFont['maxp'].numGlyphs):
				glyphOrder[i] = "glyph#%.5d" % i
				self.extraNames.append(glyphOrder[i])
		self.build_psNameMapping(ttFont)
	
	def build_psNameMapping(self, ttFont):
		mapping = {}
		allNames = {}
		for i in range(ttFont['maxp'].numGlyphs):
			glyphName = psName = self.glyphOrder[i]
			if allNames.has_key(glyphName):
				# make up a new glyphName that's unique
				n = allNames[glyphName]
				allNames[glyphName] = n + 1
				glyphName = glyphName + "#" + `n`
				self.glyphOrder[i] = glyphName
				mapping[glyphName] = psName
			else:
				allNames[glyphName] = 1
		self.mapping = mapping
	
	def decode_format_3_0(self, data, ttFont):
		# Setting self.glyphOrder to None will cause the TTFont object
		# try and construct glyph names from a Unicode cmap table.
		self.glyphOrder = None
	
	def encode_format_2_0(self, ttFont):
		numGlyphs = ttFont['maxp'].numGlyphs
		glyphOrder = ttFont.getGlyphOrder()
		assert len(glyphOrder) == numGlyphs
		indices = array.array("H")
		extraDict = {}
		extraNames = self.extraNames
		for i in range(len(extraNames)):
			extraDict[extraNames[i]] = i
		for glyphID in range(numGlyphs):
			glyphName = glyphOrder[glyphID]
			if self.mapping.has_key(glyphName):
				psName = self.mapping[glyphName]
			else:
				psName = glyphName
			if extraDict.has_key(psName):
				index = 258 + extraDict[psName]
			elif psName in standardGlyphOrder:
				index = standardGlyphOrder.index(psName)
			else:
				index = 258 + len(extraNames)
				extraDict[psName] = len(extraNames)
				extraNames.append(psName)
			indices.append(index)
		if sys.byteorder <> "big":
			indices.byteswap()
		return struct.pack(">H", numGlyphs) + indices.tostring() + packPStrings(extraNames)
	
	def toXML(self, writer, ttFont):
		formatstring, names, fixes = sstruct.getformat(postFormat)
		for name in names:
			value = getattr(self, name)
			writer.simpletag(name, value=value)
			writer.newline()
		if hasattr(self, "mapping"):
			writer.begintag("psNames")
			writer.newline()
			writer.comment("This file uses unique glyph names based on the information\n"
						"found in the 'post' table. Since these names might not be unique,\n"
						"we have to invent artificial names in case of clashes. In order to\n"
						"be able to retain the original information, we need a name to\n"
						"ps name mapping for those cases where they differ. That's what\n"
						"you see below.\n")
			writer.newline()
			items = self.mapping.items()
			items.sort()
			for name, psName in items:
				writer.simpletag("psName", name=name, psName=psName)
				writer.newline()
			writer.endtag("psNames")
			writer.newline()
		if hasattr(self, "extraNames"):
			writer.begintag("extraNames")
			writer.newline()
			writer.comment("following are the name that are not taken from the standard Mac glyph order")
			writer.newline()
			for name in self.extraNames:
				writer.simpletag("psName", name=name)
				writer.newline()
			writer.endtag("extraNames")
			writer.newline()
		if hasattr(self, "data"):
			writer.begintag("hexdata")
			writer.newline()
			writer.dumphex(self.data)
			writer.endtag("hexdata")
			writer.newline()
	
	def fromXML(self, (name, attrs, content), ttFont):
		if name not in ("psNames", "extraNames", "hexdata"):
			setattr(self, name, safeEval(attrs["value"]))
		elif name == "psNames":
			self.mapping = {}
			for element in content:
				if type(element) <> TupleType:
					continue
				name, attrs, content = element
				if name == "psName":
					self.mapping[attrs["name"]] = attrs["psName"]
		elif name == "extraNames":
			self.extraNames = []
			for element in content:
				if type(element) <> TupleType:
					continue
				name, attrs, content = element
				if name == "psName":
					self.extraNames.append(attrs["name"])
		else:
			self.data = readHex(content)


def unpackPStrings(data):
	strings = []
	index = 0
	dataLen = len(data)
	while index < dataLen:
		length = ord(data[index])
		strings.append(data[index+1:index+1+length])
		index = index + 1 + length
	return strings


def packPStrings(strings):
	data = ""
	for s in strings:
		data = data + chr(len(s)) + s
	return data

