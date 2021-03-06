import operator
import DefaultTable
import struct
from fontTools.ttLib import sfnt
from fontTools.misc.textTools import safeEval, readHex
from types import IntType, StringType


class table_C_O_L_R_(DefaultTable.DefaultTable):

	""" This table is structured so that you can treat it like a dictionary keyed by glyph name.
	ttFont['COLR'][<glyphName>] will return the color layers for any glyph
	ttFont['COLR'][<glyphName>] = <value> will set the color layers for any glyph.
	"""

	def decompile(self, data, ttFont):
		self.getGlyphName = ttFont.getGlyphName # for use in get/set item functions, for access by GID
		self.version, numBaseGlyphRecords, offsetBaseGlyphRecord, offsetLayerRecord, numLayerRecords = struct.unpack(">HHLLH", data[:14])
		assert (self.version == 0), "Version of COLR table is higher than I know how to handle"
		glyphOrder = ttFont.getGlyphOrder()
		gids = []
		layerLists = []
		glyphPos = offsetBaseGlyphRecord
		for i in range(numBaseGlyphRecords):
			gid, firstLayerIndex, numLayers = struct.unpack(">HHH", data[glyphPos:glyphPos+6])
			glyphPos += 6
			gids.append(gid)
			assert (firstLayerIndex + numLayers <= numLayerRecords)
			layerPos = offsetLayerRecord + firstLayerIndex * 4
			layers = []
			for j in range(numLayers):
				layerGid, colorID = struct.unpack(">HH", data[layerPos:layerPos+4])
				try:
					layerName = glyphOrder[layerGid]
				except IndexError:
					layerName = self.getGlyphName(layerGid)
				layerPos += 4
				layers.append(LayerRecord(layerName, colorID))
			layerLists.append(layers)

		self.ColorLayers = colorLayerLists = {}
		try:
			names = map(operator.getitem, [glyphOrder]*numBaseGlyphRecords, gids)
		except IndexError:
			getGlyphName = self.getGlyphName
			names = map(getGlyphName, gids )

		map(operator.setitem, [colorLayerLists]*numBaseGlyphRecords, names, layerLists)


	def compile(self, ttFont):
		ordered = []
		ttFont.getReverseGlyphMap(rebuild=1)
		glyphNames = self.ColorLayers.keys()
		for glyphName in glyphNames:
			try:
				gid = ttFont.getGlyphID(glyphName)
			except:
				assert 0, "COLR table contains a glyph name not in ttFont.getGlyphNames(): " + str(glyphName)
			ordered.append([gid, glyphName, self.ColorLayers[glyphName]])
		ordered.sort()

		glyphMap = []
		layerMap = []
		for (gid, glyphName, layers) in ordered:
			glyphMap.append(struct.pack(">HHH", gid, len(layerMap), len(layers)))
			for layer in layers:
				layerMap.append(struct.pack(">HH", ttFont.getGlyphID(layer.name), layer.colorID))

		dataList = [struct.pack(">HHLLH", self.version, len(glyphMap), 14, 14+6*len(glyphMap), len(layerMap))]
		dataList.extend(glyphMap)
		dataList.extend(layerMap)
		data = "".join(dataList)
		return data

	def toXML(self, writer, ttFont):
		writer.simpletag("version", value=self.version)
		writer.newline()
		ordered = []
		glyphNames = self.ColorLayers.keys()
		for glyphName in glyphNames:
			try:
				gid = ttFont.getGlyphID(glyphName)
			except:
				assert 0, "COLR table contains a glyph name not in ttFont.getGlyphNames(): " + str(glyphName)
			ordered.append([gid, glyphName, self.ColorLayers[glyphName]])
		ordered.sort()
		for entry in ordered:
			writer.begintag("ColorGlyph", name=entry[1])
			writer.newline()
			for layer in entry[2]:
				layer.toXML(writer, ttFont)
			writer.endtag("ColorGlyph")
			writer.newline()

	def fromXML(self, (name, attrs, content), ttFont):
		if not hasattr(self, "ColorLayers"):
			self.ColorLayers = {}
		self.getGlyphName = ttFont.getGlyphName # for use in get/set item functions, for access by GID
		if name == "ColorGlyph":
			glyphName = attrs["name"]
			for element in content:
				if isinstance(element, StringType):
					continue
			layers = []
			for element in content:
				if isinstance(element, StringType):
					continue
				layer = LayerRecord()
				layer.fromXML(element, ttFont)
				layers.append (layer)
			operator.setitem(self, glyphName, layers)
		elif attrs.has_key("value"):
			value =  safeEval(attrs["value"])
			setattr(self, name, value)


	def __getitem__(self, glyphSelector):
		if type(glyphSelector) == IntType:
			# its a gid, convert to glyph name
			glyphSelector = self.getGlyphName(glyphSelector)

		if not self.ColorLayers.has_key(glyphSelector):
			return None
			
		return self.ColorLayers[glyphSelector]

	def __setitem__(self, glyphSelector, value):
		if type(glyphSelector) == IntType:
			# its a gid, convert to glyph name
			glyphSelector = self.getGlyphName(glyphSelector)

		if  value:
			self.ColorLayers[glyphSelector] = value
		elif self.ColorLayers.has_key(glyphSelector):
			del self.ColorLayers[glyphSelector]

class LayerRecord:

	def __init__(self, name = None, colorID = None):
		self.name = name
		self.colorID = colorID

	def toXML(self, writer, ttFont):
		writer.simpletag("layer", name=self.name, colorID=self.colorID)
		writer.newline()

	def fromXML(self, (eltname, attrs, content), ttFont):
		for (name, value) in attrs.items():
			if name == "name":
				if type(value) == IntType:
					value = ttFont.getGlyphName(value)
				setattr(self, name, value)
			else:
				try:
					value = safeEval(value)
				except OverflowError:
					value = long(value)
				setattr(self, name, value)
