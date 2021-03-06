
import DefaultTable
import string
import struct
import sstruct
import itertools
from types import TupleType
from collections import deque
from fontTools.misc.textTools import safeEval
from BitmapGlyphMetrics import BigGlyphMetrics, bigGlyphMetricsFormat, SmallGlyphMetrics, smallGlyphMetricsFormat

eblcHeaderFormat = """
	> # big endian
	version:  16.16F
	numSizes: I
"""
# The table format string is split to handle sbitLineMetrics simply.
bitmapSizeTableFormatPart1 = """
	> # big endian
	indexSubTableArrayOffset: I
	indexTablesSize:          I
	numberOfIndexSubTables:   I
	colorRef:                 I
"""
# The compound type for hori and vert.
sbitLineMetricsFormat = """
	> # big endian
	ascender:              b
	descender:             b
	widthMax:              B
	caretSlopeNumerator:   b
	caretSlopeDenominator: b
	caretOffset:           b
	minOriginSB:           b
	minAdvanceSB:          b
	maxBeforeBL:           b
	minAfterBL:            b
	pad1:                  b
	pad2:                  b
"""
# hori and vert go between the two parts.
bitmapSizeTableFormatPart2 = """
	> # big endian
	startGlyphIndex: H
	endGlyphIndex:   H
	ppemX:           B
	ppemY:           B
	bitDepth:        B
	flags:           b
"""

indexSubTableArrayFormat = ">HHL"
indexSubTableArraySize = struct.calcsize(indexSubTableArrayFormat)

indexSubHeaderFormat = ">HHL"
indexSubHeaderSize = struct.calcsize(indexSubHeaderFormat)

codeOffsetPairFormat = ">HH"
codeOffsetPairSize = struct.calcsize(codeOffsetPairFormat)

class table_E_B_L_C_(DefaultTable.DefaultTable):

	dependencies = ['EBDT']

	# This method can be overridden in subclasses to support new formats
	# without changing the other implementation. Also can be used as a
	# convenience method for coverting a font file to an alternative format.
	def getIndexFormatClass(self, indexFormat):
		return eblc_sub_table_classes[indexFormat]

	def decompile(self, data, ttFont):

		# Save the original data because offsets are from the start of the table.
		origData = data

		dummy, data = sstruct.unpack2(eblcHeaderFormat, data, self)

		self.strikes = []
		for curStrikeIndex in xrange(self.numSizes):
			curStrike = Strike()
			self.strikes.append(curStrike)
			curTable = curStrike.bitmapSizeTable
			dummy, data = sstruct.unpack2(bitmapSizeTableFormatPart1, data, curTable)
			for metric in ('hori', 'vert'):
				metricObj = SbitLineMetrics()
				vars(curTable)[metric] = metricObj
				dummy, data = sstruct.unpack2(sbitLineMetricsFormat, data, metricObj)
			dummy, data = sstruct.unpack2(bitmapSizeTableFormatPart2, data, curTable)

		for curStrike in self.strikes:
			curTable = curStrike.bitmapSizeTable
			for subtableIndex in xrange(curTable.numberOfIndexSubTables):
				lowerBound = curTable.indexSubTableArrayOffset + subtableIndex * indexSubTableArraySize
				upperBound = lowerBound + indexSubTableArraySize
				data = origData[lowerBound:upperBound]

				tup = struct.unpack(indexSubTableArrayFormat, data)
				(firstGlyphIndex, lastGlyphIndex, additionalOffsetToIndexSubtable) = tup
				offsetToIndexSubTable = curTable.indexSubTableArrayOffset + additionalOffsetToIndexSubtable
				data = origData[offsetToIndexSubTable:]

				tup = struct.unpack(indexSubHeaderFormat, data[:indexSubHeaderSize])
				(indexFormat, imageFormat, imageDataOffset) = tup

				indexFormatClass = self.getIndexFormatClass(indexFormat)
				indexSubTable = indexFormatClass(data[indexSubHeaderSize:], ttFont)
				indexSubTable.firstGlyphIndex = firstGlyphIndex
				indexSubTable.lastGlyphIndex = lastGlyphIndex
				indexSubTable.additionalOffsetToIndexSubtable = additionalOffsetToIndexSubtable
				indexSubTable.indexFormat = indexFormat
				indexSubTable.imageFormat = imageFormat
				indexSubTable.imageDataOffset = imageDataOffset
				curStrike.indexSubTables.append(indexSubTable)

	def compile(self, ttFont):

		dataList = []
		self.numSizes = len(self.strikes)
		dataList.append(sstruct.pack(eblcHeaderFormat, self))

		# Data size of the header + bitmapSizeTable needs to be calculated
		# in order to form offsets. This value will hold the size of the data
		# in dataList after all the data is consolidated in dataList.
		dataSize = len(dataList[0])

		# The table will be structured in the following order:
		# (0) header
		# (1) Each bitmapSizeTable [1 ... self.numSizes]
		# (2) Alternate between indexSubTableArray and indexSubTable
		#     for each bitmapSizeTable present.
		#
		# The issue is maintaining the proper offsets when table information
		# gets moved around. All offsets and size information must be recalculated
		# when building the table to allow editing within ttLib and also allow easy
		# import/export to and from XML. All of this offset information is lost
		# when exporting to XML so everything must be calculated fresh so importing
		# from XML will work cleanly. Only byte offset and size information is
		# calculated fresh. Count information like numberOfIndexSubTables is
		# checked through assertions. If the information in this table was not
		# touched or was changed properly then these types of values should match.
		#
		# The table will be rebuilt the following way:
		# (0) Precompute the size of all the bitmapSizeTables. This is needed to
		#     compute the offsets properly.
		# (1) For each bitmapSizeTable compute the indexSubTable and
		#    	indexSubTableArray pair. The indexSubTable must be computed first
		#     so that the offset information in indexSubTableArray can be
		#     calculated. Update the data size after each pairing.
		# (2) Build each bitmapSizeTable.
		# (3) Consolidate all the data into the main dataList in the correct order.

		for curStrike in self.strikes:
			dataSize += sstruct.calcsize(bitmapSizeTableFormatPart1)
			dataSize += len(('hori', 'vert')) * sstruct.calcsize(sbitLineMetricsFormat)
			dataSize += sstruct.calcsize(bitmapSizeTableFormatPart2)

		indexSubTablePairDataList = []
		for curStrike in self.strikes:
			curTable = curStrike.bitmapSizeTable
			curTable.numberOfIndexSubTables = len(curStrike.indexSubTables)
			curTable.indexSubTableArrayOffset = dataSize

			# Precompute the size of the indexSubTableArray. This information
			# is important for correctly calculating the new value for
			# additionalOffsetToIndexSubtable.
			sizeOfSubTableArray = curTable.numberOfIndexSubTables * indexSubTableArraySize
			lowerBound = dataSize
			dataSize += sizeOfSubTableArray
			upperBound = dataSize

			indexSubTableDataList = []
			for indexSubTable in curStrike.indexSubTables:
				indexSubTable.additionalOffsetToIndexSubtable = dataSize - curTable.indexSubTableArrayOffset
				glyphIds = map(ttFont.getGlyphID, indexSubTable.names)
				indexSubTable.firstGlyphIndex = min(glyphIds)
				indexSubTable.lastGlyphIndex = max(glyphIds)
				data = indexSubTable.compile(ttFont)
				indexSubTableDataList.append(data)
				dataSize += len(data)
			curTable.startGlyphIndex = min(ist.firstGlyphIndex for ist in curStrike.indexSubTables)
			curTable.endGlyphIndex = max(ist.lastGlyphIndex for ist in curStrike.indexSubTables)

			for i in curStrike.indexSubTables:
				data = struct.pack(indexSubHeaderFormat, i.firstGlyphIndex, i.lastGlyphIndex, i.additionalOffsetToIndexSubtable)
				indexSubTablePairDataList.append(data)
			indexSubTablePairDataList.extend(indexSubTableDataList)
			curTable.indexTablesSize = dataSize - curTable.indexSubTableArrayOffset

		for curStrike in self.strikes:
			curTable = curStrike.bitmapSizeTable
			data = sstruct.pack(bitmapSizeTableFormatPart1, curTable)
			dataList.append(data)
			for metric in ('hori', 'vert'):
				metricObj = vars(curTable)[metric]
				data = sstruct.pack(sbitLineMetricsFormat, metricObj)
				dataList.append(data)
			data = sstruct.pack(bitmapSizeTableFormatPart2, curTable)
			dataList.append(data)
		dataList.extend(indexSubTablePairDataList)

		return string.join(dataList, "")

	def toXML(self, writer, ttFont):
		writer.simpletag('header', [('version', self.version)])
		writer.newline()
		for curIndex, curStrike in enumerate(self.strikes):
			curStrike.toXML(curIndex, writer, ttFont)

	def fromXML(self, (name, attrs, content), ttFont):
		if name == 'header':
			self.version = safeEval(attrs['version'])
		elif name == 'strike':
			if not hasattr(self, 'strikes'):
				self.strikes = []
			strikeIndex = safeEval(attrs['index'])
			curStrike = Strike()
			curStrike.fromXML((name, attrs, content), ttFont, self)

			# Grow the strike array to the appropriate size. The XML format
			# allows for the strike index value to be out of order.
			if strikeIndex >= len(self.strikes):
				self.strikes += [None] * (strikeIndex + 1 - len(self.strikes))
			assert self.strikes[strikeIndex] == None, "Duplicate strike EBLC indices."
			self.strikes[strikeIndex] = curStrike

class Strike:

	def __init__(self):
		self.bitmapSizeTable = BitmapSizeTable()
		self.indexSubTables = []

	def toXML(self, strikeIndex, writer, ttFont):
		writer.begintag('strike', [('index', strikeIndex)])
		writer.newline()
		self.bitmapSizeTable.toXML(writer, ttFont)
		writer.comment('GlyphIds are written but not read. The firstGlyphIndex and\nlastGlyphIndex values will be recalculated by the compiler.')
		writer.newline()
		for indexSubTable in self.indexSubTables:
			indexSubTable.toXML(writer, ttFont)
		writer.endtag('strike')
		writer.newline()

	def fromXML(self, (name, attrs, content), ttFont, locator):
		for element in content:
			if type(element) != TupleType:
				continue
			name, attrs, content = element
			if name == 'bitmapSizeTable':
				self.bitmapSizeTable.fromXML(element, ttFont)
			elif name.startswith(_indexSubTableSubclassPrefix):
				indexFormat = safeEval(name[len(_indexSubTableSubclassPrefix):])
				indexFormatClass = locator.getIndexFormatClass(indexFormat)
				indexSubTable = indexFormatClass(None, None)
				indexSubTable.indexFormat = indexFormat
				indexSubTable.fromXML(element, ttFont)
				self.indexSubTables.append(indexSubTable)


class BitmapSizeTable:

	# Returns all the simple metric names that bitmap size table
	# cares about in terms of XML creation.
	def _getXMLMetricNames(self):
		dataNames = sstruct.getformat(bitmapSizeTableFormatPart1)[1]
		dataNames = dataNames + sstruct.getformat(bitmapSizeTableFormatPart2)[1]
		# Skip the first 3 data names because they are byte offsets and counts.
		return dataNames[3:]

	def toXML(self, writer, ttFont):
		writer.begintag('bitmapSizeTable')
		writer.newline()
		for metric in ('hori', 'vert'):
			getattr(self, metric).toXML(metric, writer, ttFont)
		for metricName in self._getXMLMetricNames():
			writer.simpletag(metricName, value=getattr(self, metricName))
			writer.newline()
		writer.endtag('bitmapSizeTable')
		writer.newline()

	def fromXML(self, (name, attrs, content), ttFont):
		# Create a lookup for all the simple names that make sense to
		# bitmap size table. Only read the information from these names.
		dataNames = set(self._getXMLMetricNames())
		for element in content:
			if type(element) != TupleType:
				continue
			name, attrs, content = element
			if name == 'sbitLineMetrics':
				direction = attrs['direction']
				assert direction in ('hori', 'vert'), "SbitLineMetrics direction specified invalid."
				metricObj = SbitLineMetrics()
				metricObj.fromXML(element, ttFont)
				vars(self)[direction] = metricObj
			elif name in dataNames:
				vars(self)[name] = safeEval(attrs['value'])
			else:
				print "Warning: unknown name '%s' being ignored in BitmapSizeTable." % name


class SbitLineMetrics:

	def toXML(self, name, writer, ttFont):
		writer.begintag('sbitLineMetrics', [('direction', name)])
		writer.newline()
		for metricName in sstruct.getformat(sbitLineMetricsFormat)[1]:
			writer.simpletag(metricName, value=getattr(self, metricName))
			writer.newline()
		writer.endtag('sbitLineMetrics')
		writer.newline()

	def fromXML(self, (name, attrs, content), ttFont):
		metricNames = set(sstruct.getformat(sbitLineMetricsFormat)[1])
		for element in content:
			if type(element) != TupleType:
				continue
			name, attrs, content = element
			if name in metricNames:
				vars(self)[name] = safeEval(attrs['value'])

# Important information about the naming scheme. Used for identifying subtables.
_indexSubTableSubclassPrefix = 'eblc_index_sub_table_'

class EblcIndexSubTable:

	def __init__(self, data, ttFont):
		self.data = data
		self.ttFont = ttFont

	def __getattr__(self, attr):
		# Allow lazy decompile.
		if attr[:2] == '__':
			raise AttributeError, attr
		if self.data == None:
			raise AttributeError, attr
		self.decompile()
		self.data = None
		self.ttFont = None
		return getattr(self, attr)

	# This method just takes care of the indexSubHeader. Implementing subclasses
	# should call it to compile the indexSubHeader and then continue compiling
	# the remainder of their unique format.
	def compile(self, ttFont):
		return struct.pack(indexSubHeaderFormat, self.indexFormat, self.imageFormat, self.imageDataOffset)

	# Creates the XML for bitmap glyphs. Each index sub table basically makes
	# the same XML except for specific metric information that is written
	# out via a method call that a subclass implements optionally.
	def toXML(self, writer, ttFont):
		writer.begintag(self.__class__.__name__, [
				('imageFormat', self.imageFormat),
				('firstGlyphIndex', self.firstGlyphIndex),
				('lastGlyphIndex', self.lastGlyphIndex),
				])
		writer.newline()
		self.writeMetrics(writer, ttFont)
		# Write out the names as thats all thats needed to rebuild etc.
		# For font debugging of consecutive formats the ids are also written.
		# The ids are not read when moving from the XML format.
		glyphIds = map(ttFont.getGlyphID, self.names)
		for glyphName, glyphId in itertools.izip(self.names, glyphIds):
			writer.simpletag('glyphLoc', name=glyphName, id=glyphId)
			writer.newline()
		writer.endtag(self.__class__.__name__)
		writer.newline()

	def fromXML(self, (name, attrs, content), ttFont):
		# Read all the attributes. Even though the glyph indices are
		# recalculated, they are still read in case there needs to
		# be an immediate export of the data.
		self.imageFormat = safeEval(attrs['imageFormat'])
		self.firstGlyphIndex = safeEval(attrs['firstGlyphIndex'])
		self.lastGlyphIndex = safeEval(attrs['lastGlyphIndex'])

		self.readMetrics((name, attrs, content), ttFont)

		self.names = []
		for element in content:
			if type(element) != TupleType:
				continue
			name, attrs, content = element
			if name == 'glyphLoc':
				self.names.append(attrs['name'])

	# A helper method that writes the metrics for the index sub table. It also
	# is responsible for writing the image size for fixed size data since fixed
	# size is not recalculated on compile. Default behavior is to do nothing.
	def writeMetrics(self, writer, ttFont):
		pass

	# A helper method that is the inverse of writeMetrics.
	def readMetrics(self, (name, attrs, content), ttFont):
		pass

	# This method is for fixed glyph data sizes. There are formats where
	# the glyph data is fixed but are actually composite glyphs. To handle
	# this the font spec in indexSubTable makes the data the size of the
	# fixed size by padding the component arrays. This function abstracts
	# out this padding process. Input is data unpadded. Output is data
	# padded only in fixed formats. Default behavior is to return the data.
	def padBitmapData(self, data):
		return data

	# Remove any of the glyph locations and names that are flagged as skipped.
	# This only occurs in formats {1,3}.
	def removeSkipGlyphs(self):
		# Determines if a name, location pair is a valid data location.
		# Skip glyphs are marked when the size is equal to zero.
		def isValidLocation((name, (startByte, endByte))):
			return startByte < endByte
		# Remove all skip glyphs.
		dataPairs = filter(isValidLocation, zip(self.names, self.locations))
		self.names, self.locations = map(list, zip(*dataPairs))

# A closure for creating a custom mixin. This is done because formats 1 and 3
# are very similar. The only difference between them is the size per offset
# value. Code put in here should handle both cases generally.
def _createOffsetArrayIndexSubTableMixin(formatStringForDataType):

	# Prep the data size for the offset array data format.
	dataFormat = '>'+formatStringForDataType
	offsetDataSize = struct.calcsize(dataFormat)

	class OffsetArrayIndexSubTableMixin:

		def decompile(self):

			numGlyphs = self.lastGlyphIndex - self.firstGlyphIndex + 1
			indexingOffsets = [glyphIndex * offsetDataSize for glyphIndex in xrange(numGlyphs+2)]
			indexingLocations = zip(indexingOffsets, indexingOffsets[1:])
			offsetArray = [struct.unpack(dataFormat, self.data[slice(*loc)])[0] for loc in indexingLocations]

			glyphIds = range(self.firstGlyphIndex, self.lastGlyphIndex+1)
			modifiedOffsets = [offset + self.imageDataOffset for offset in offsetArray]
			self.locations = zip(modifiedOffsets, modifiedOffsets[1:])

			self.names = map(self.ttFont.getGlyphName, glyphIds)
			self.removeSkipGlyphs()

		def compile(self, ttFont):
			# First make sure that all the data lines up properly. Formats 1 and 3
			# must have all its data lined up consecutively. If not this will fail.
			for curLoc, nxtLoc in itertools.izip(self.locations, self.locations[1:]):
				assert curLoc[1] == nxtLoc[0], "Data must be consecutive in indexSubTable offset formats"

			glyphIds = map(ttFont.getGlyphID, self.names)
			# Make sure that all ids are sorted strictly increasing.
			assert all(glyphIds[i] < glyphIds[i+1] for i in xrange(len(glyphIds)-1))

			# Run a simple algorithm to add skip glyphs to the data locations at
			# the places where an id is not present.
			idQueue = deque(glyphIds)
			locQueue = deque(self.locations)
			allGlyphIds = range(self.firstGlyphIndex, self.lastGlyphIndex+1)
			allLocations = []
			for curId in allGlyphIds:
				if curId != idQueue[0]:
					allLocations.append((locQueue[0][0], locQueue[0][0]))
				else:
					idQueue.popleft()
					allLocations.append(locQueue.popleft())

			# Now that all the locations are collected, pack them appropriately into
			# offsets. This is the form where offset[i] is the location and
			# offset[i+1]-offset[i] is the size of the data location.
			offsets = list(allLocations[0]) + [loc[1] for loc in allLocations[1:]]
			# Image data offset must be less than or equal to the minimum of locations.
			# This offset may change the value for round tripping but is safer and
			# allows imageDataOffset to not be required to be in the XML version.
			self.imageDataOffset = min(offsets)
			offsetArray = [offset - self.imageDataOffset for offset in offsets]

			dataList = [EblcIndexSubTable.compile(self, ttFont)]
			dataList += [struct.pack(dataFormat, offsetValue) for offsetValue in offsetArray]
			# Take care of any padding issues. Only occurs in format 3.
			if offsetDataSize * len(dataList) % 4 != 0:
				dataList.append(struct.pack(dataFormat, 0))
			return string.join(dataList, "")

	return OffsetArrayIndexSubTableMixin

# A Mixin for functionality shared between the different kinds
# of fixed sized data handling. Both kinds have big metrics so
# that kind of special processing is also handled in this mixin.
class FixedSizeIndexSubTableMixin:

	def writeMetrics(self, writer, ttFont):
		writer.simpletag('imageSize', value=self.imageSize)
		writer.newline()
		self.metrics.toXML(writer, ttFont)

	def readMetrics(self, (name, attrs, content), ttFont):
		for element in content:
			if type(element) != TupleType:
				continue
			name, attrs, content = element
			if name == 'imageSize':
				self.imageSize = safeEval(attrs['value'])
			elif name == BigGlyphMetrics.__name__:
				self.metrics = BigGlyphMetrics()
				self.metrics.fromXML(element, ttFont)
			elif name == SmallGlyphMetrics.__name__:
				print "Warning: SmallGlyphMetrics being ignored in format %d." % self.indexFormat

	def padBitmapData(self, data):
		# Make sure that the data isn't bigger than the fixed size.
		assert len(data) <= self.imageSize, "Data in indexSubTable format %d must be less than the fixed size." % self.indexFormat
		# Pad the data so that it matches the fixed size.
		pad = (self.imageSize - len(data)) * '\0'
		return data + pad

class eblc_index_sub_table_1(_createOffsetArrayIndexSubTableMixin('L'), EblcIndexSubTable):
	pass

class eblc_index_sub_table_2(FixedSizeIndexSubTableMixin, EblcIndexSubTable):

	def decompile(self):
		(self.imageSize,) = struct.unpack(">L", self.data[:4])
		self.metrics = BigGlyphMetrics()
		sstruct.unpack2(bigGlyphMetricsFormat, self.data[4:], self.metrics)
		glyphIds = range(self.firstGlyphIndex, self.lastGlyphIndex+1)
		offsets = [self.imageSize * i + self.imageDataOffset for i in xrange(len(glyphIds)+1)]
		self.locations = zip(offsets, offsets[1:])
		self.names = map(self.ttFont.getGlyphName, glyphIds)

	def compile(self, ttFont):
		glyphIds = map(ttFont.getGlyphID, self.names)
		# Make sure all the ids are consecutive. This is required by Format 2.
		assert glyphIds == range(self.firstGlyphIndex, self.lastGlyphIndex+1), "Format 2 ids must be consecutive."
		self.imageDataOffset = min(zip(*self.locations)[0])

		dataList = [EblcIndexSubTable.compile(self, ttFont)]
		dataList.append(struct.pack(">L", self.imageSize))
		dataList.append(sstruct.pack(bigGlyphMetricsFormat, self.metrics))
		return string.join(dataList, "")

class eblc_index_sub_table_3(_createOffsetArrayIndexSubTableMixin('H'), EblcIndexSubTable):
	pass

class eblc_index_sub_table_4(EblcIndexSubTable):

	def decompile(self):

		(numGlyphs,) = struct.unpack(">L", self.data[:4])
		data = self.data[4:]
		indexingOffsets = [glyphIndex * codeOffsetPairSize for glyphIndex in xrange(numGlyphs+2)]
		indexingLocations = zip(indexingOffsets, indexingOffsets[1:])
		glyphArray = [struct.unpack(codeOffsetPairFormat, data[slice(*loc)]) for loc in indexingLocations]
		glyphIds, offsets = map(list, zip(*glyphArray))
		# There are one too many glyph ids. Get rid of the last one.
		glyphIds.pop()

		offsets = [offset + self.imageDataOffset for offset in offsets]
		self.locations = zip(offsets, offsets[1:])
		self.names = map(self.ttFont.getGlyphName, glyphIds)

	def compile(self, ttFont):
		# First make sure that all the data lines up properly. Format 4
		# must have all its data lined up consecutively. If not this will fail.
		for curLoc, nxtLoc in itertools.izip(self.locations, self.locations[1:]):
			assert curLoc[1] == nxtLoc[0], "Data must be consecutive in indexSubTable format 4"

		offsets = list(self.locations[0]) + [loc[1] for loc in self.locations[1:]]
		# Image data offset must be less than or equal to the minimum of locations.
		# Resetting this offset may change the value for round tripping but is safer
		# and allows imageDataOffset to not be required to be in the XML version.
		self.imageDataOffset = min(offsets)
		offsets = [offset - self.imageDataOffset for offset in offsets]
		glyphIds = map(ttFont.getGlyphID, self.names)
		# Create an iterator over the ids plus a padding value.
		idsPlusPad = list(itertools.chain(glyphIds, [0]))

		dataList = [EblcIndexSubTable.compile(self, ttFont)]
		dataList.append(struct.pack(">L", len(glyphIds)))
		tmp = [struct.pack(codeOffsetPairFormat, *cop) for cop in itertools.izip(idsPlusPad, offsets)]
		dataList += tmp
		data = string.join(dataList, "")
		return data

class eblc_index_sub_table_5(FixedSizeIndexSubTableMixin, EblcIndexSubTable):

	def decompile(self):
		self.origDataLen = 0
		(self.imageSize,) = struct.unpack(">L", self.data[:4])
		data = self.data[4:]
		self.metrics, data = sstruct.unpack2(bigGlyphMetricsFormat, data, BigGlyphMetrics())
		(numGlyphs,) = struct.unpack(">L", data[:4])
		data = data[4:]
		glyphIds = [struct.unpack(">H", data[2*i:2*(i+1)])[0] for i in xrange(numGlyphs)]

		offsets = [self.imageSize * i + self.imageDataOffset for i in xrange(len(glyphIds)+1)]
		self.locations = zip(offsets, offsets[1:])
		self.names = map(self.ttFont.getGlyphName, glyphIds)

	def compile(self, ttFont):
		self.imageDataOffset = min(zip(*self.locations)[0])
		dataList = [EblcIndexSubTable.compile(self, ttFont)]
		dataList.append(struct.pack(">L", self.imageSize))
		dataList.append(sstruct.pack(bigGlyphMetricsFormat, self.metrics))
		glyphIds = map(ttFont.getGlyphID, self.names)
		dataList.append(struct.pack(">L", len(glyphIds)))
		dataList += [struct.pack(">H", curId) for curId in glyphIds]
		if len(glyphIds) % 2 == 1:
			dataList.append(struct.pack(">H", 0))
		return string.join(dataList, "")

# Dictionary of indexFormat to the class representing that format.
eblc_sub_table_classes = {
		1: eblc_index_sub_table_1,
		2: eblc_index_sub_table_2,
		3: eblc_index_sub_table_3,
		4: eblc_index_sub_table_4,
		5: eblc_index_sub_table_5,
	}
