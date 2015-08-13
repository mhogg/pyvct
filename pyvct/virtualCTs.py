# -*- coding: utf-8 -*-

# Copyright (C) 2015 Michael Hogg

# This file is part of pyvct - See LICENSE.txt for information on usage and redistribution

import os
from abaqus import session
from abaqusConstants import ELEMENT_NODAL
from cythonMods import createElementMap
import elemTypes as et
import copy
from odbAccess import OdbMeshElementType
import numpy as np

# ~~~~~~~~~~

def convert3Dto1Dindex(i,j,k,NX,NY,NZ):
    """Converts 3D array index to 1D array index"""
    index = i+j*NX+k*NX*NY
    return index
    
# ~~~~~~~~~~
  
def convert1Dto3Dindex(index,NX,NY,NZ):
    """Converts 1D array index to 1D array index"""
    k = index / (NX*NY)
    j = (index - k*NX*NY) / NX
    i = index - k*NX*NY - j*NX
    return [i,j,k]
    
# ~~~~~~~~~~   

def transformPoint(TM,point):
    """Transforms point using supplied transform"""
    point = np.append(point,1.0)
    return np.dot(TM,point)[:3]
    
# ~~~~~~~~~~      

def createTransformationMatrix(Ma,Mb,Vab,rel='a'):
    """
    Creates a transformation matrix that can be used to transform a point from csys a to csys b.
    Ma  = 3x3 matrix containing unit vectors of orthogonal coordinate directions for csys a
    Mb  = 3x3 matrix containing unit vectors of orthogonal coordinate directions for csys b
    Vab = 3x1 vector from origin of csys a to csys b
    rel = 'a' or 'b' = Character to indicate if Vab is relative to csys a or csys b
    """
    if rel!='a' and rel!='b': return None
    a1,a2,a3 = Ma
    b1,b2,b3 = Mb
    # Rotation matrix
    R = np.identity(4,np.float)
    R[0,0:3] = [np.dot(b1,a1), np.dot(b1,a2), np.dot(b1,a3)]
    R[1,0:3] = [np.dot(b2,a1), np.dot(b2,a2), np.dot(b2,a3)]
    R[2,0:3] = [np.dot(b3,a1), np.dot(b3,a2), np.dot(b3,a3)]    
    # Transformation matrix
    if rel=='b':
        Vab = np.append(Vab,1.0)
        Vab = np.dot(R.T,Vab)[0:3]
    T = np.identity(4,np.float)     
    T[0:3,3] = -Vab       
    # Transformation matrix
    return np.dot(R,T)
    
# ~~~~~~~~~~ 

def getTMfromCsys(odb,csysName):
    if csysName=='GLOBAL': return None
    # Parse coordinate system name
    csysName = csysName.split(r'(')[0].strip()
    # Get ABAQUS datumCsys
    lcsys = None
    # Check odb csyses
    if csysName in odb.rootAssembly.datumCsyses.keys(): 
        lcsys = odb.rootAssembly.datumCsyses[csysName]
    # Check scratch odb csyses
    if odb.path in session.scratchOdbs.keys():
        if csysName in session.scratchOdbs[odb.path].rootAssembly.datumCsyses.keys():
            lcsys = session.scratchOdbs[odb.path].rootAssembly.datumCsyses[csysName]
    if lcsys==None: return None
    # Global coordinate system
    Og = np.zeros(3)
    Mg = np.identity(3)
    # Local coordinate system
    Ol    = lcsys.origin
    Ml    = np.zeros((3,3))
    Ml[0] = lcsys.xAxis/np.linalg.norm(lcsys.xAxis) # NOTE: This should already be a unit vector
    Ml[1] = lcsys.yAxis/np.linalg.norm(lcsys.yAxis) #       Shouldn't need to normalise
    Ml[2] = lcsys.zAxis/np.linalg.norm(lcsys.zAxis)
    # Create transformation matrix
    Vgl = Ol-Og
    TM  = createTransformationMatrix(Mg,Ml,Vgl,rel='a')
    return TM
        
# ~~~~~~~~~~            

def parseRegionSetName(regionSetName):
    """ Get region and setName from regionSetName """ 
    if '.' in regionSetName: region,setName = regionSetName.split('.')
    else:                    region,setName = 'Assembly',regionSetName   
    return region,setName

# ~~~~~~~~~~   
    
def getElements(odb,regionSetName):
    
    """Get element type and number of nodes per element"""
        
    # Get region set and elements
    region,setName = parseRegionSetName(regionSetName)
    if region=='Assembly':
        setRegion =  odb.rootAssembly.elementSets[regionSetName]
        if type(setRegion.elements[0])==OdbMeshElementType:       
            elements = setRegion.elements        
        else:
            elements=[]
            for meshElemArray in setRegion.elements:
                for e in meshElemArray:
                    elements.append(e)
    else:
        if setName=='ALL':
            setRegion = odb.rootAssembly.instances[region]
            elements  = setRegion.elements
        else:
            setRegion = odb.rootAssembly.instances[region].elementSets[setName]
            elements  = setRegion.elements
    
    # Get part information: (1) instance names, (2) element types and (3) number of each element type 
    partInfo={}
    for e in elements: 
        if not partInfo.has_key(e.instanceName): partInfo[e.instanceName]={}
        if not partInfo[e.instanceName].has_key(e.type): partInfo[e.instanceName][e.type]=0
        partInfo[e.instanceName][e.type]+=1  
        
    # Put all element types from all part instances in a list
    eTypes = []
    for k1 in partInfo.keys():
        for k2 in partInfo[k1].keys(): eTypes.append(k2)
    eTypes = dict.fromkeys(eTypes,1).keys()
        
    # Check that elements are supported
    usTypes=[]
    for eType in eTypes:
        if not any([True for seType in et.seTypes.keys() if seType==eType]):
            usTypes.append(str(eType))
    if len(usTypes)>0:
        if len(usTypes)==1: strvars = ('',usTypes[0],regionSetName,'is')
        else:               strvars = ('s',', '.join(usTypes),regionSetName,'are') 
        print '\nElement type%s %s in region %s %s not supported' % strvars
        return None
    
    return partInfo, setRegion, elements
       
# ~~~~~~~~~~      

def getPartData(odb,regionSetName,TM):

    """Get region data based on original (undeformed) coordinates"""

    # Get elements and part info
    result = getElements(odb,regionSetName)
    if result==None: return None
    else:
        regionInfo, regionSet, elements = result
        numElems = len(elements)
        ec = dict([(ename,eclass()) for ename,eclass in et.seTypes.items()])

    # Create empty dictionary,array to store element data 
    elemData = copy.deepcopy(regionInfo)
    for instName in elemData.keys():
        for k,v in elemData[instName].items():
            elemData[instName][k] = np.zeros(v,dtype=[('label','|i4'),('econn','|i4',(ec[k].numNodes,))])
    eCount      = dict([(k1,dict([k2,0] for k2 in regionInfo[k1].keys())) for k1 in regionInfo.keys()])     
    setNodeLabs = dict([(k,{}) for k in regionInfo.keys()])    
    # Create a list of element connectivities (list of nodes connected to each element)    
    for e in xrange(numElems):
        
        elem  = elements[e]
        eConn = elem.connectivity
        eInst = elem.instanceName
        eType = elem.type
        
        eIndex = eCount[eInst][eType]
        elemData[eInst][eType][eIndex] = (elem.label,eConn)
        eCount[eInst][eType] +=1  
        
        for n in eConn:        
            setNodeLabs[eInst][n] = 1
    
    numSetNodes = np.sum([len(setNodeLabs[k]) for k in setNodeLabs.keys()])
    setNodes    = np.zeros(numSetNodes,dtype=[('instName','|a80'),('label','|i4'),('coord','|f4',(3,))])    
    nodeCount   = 0
    for instName in setNodeLabs.keys():
        inst  = odb.rootAssembly.instances[instName]
        nodes = inst.nodes
        numNodes = len(nodes)
        for n in xrange(numNodes):
            node  = nodes[n]
            label = node.label
            if label in setNodeLabs[instName]:
                setNodes[nodeCount] = (instName,label,node.coordinates)
                nodeCount+=1
    
    # Transform the coordinates from the global csys to the local csys
    if TM is not None:
        print 'TM is not None'
        for i in xrange(numSetNodes):
            setNodes['coord'][i] = transformPoint(TM,setNodes['coord'][i])
        
    # Get bounding box
    low  = np.min(setNodes['coord'],axis=0)
    upp  = np.max(setNodes['coord'],axis=0) 
    bbox = (low,upp)

    # Convert setNodes to a dictionary for fast indexing by node label
    setNodeList = dict([(k,{}) for k in regionInfo.keys()])    
    for instName in setNodeList.keys():
        indx = np.where(setNodes['instName']==instName)
        setNodeList[instName] = dict(zip(setNodes[indx]['label'],setNodes[indx]['coord']))      
    
    return regionSet,elemData,setNodeList,bbox
   
# ~~~~~~~~~~ 

def checkDependencies():
    """Check pyvxray dependencies are available"""        
    try:
        from dicom.dataset import Dataset, FileDataset
    except: 
        print 'Error: Cannot load pydicom package'
        return False
    return True
    
# ~~~~~~~~~~

def createVirtualCT(odbName,bRegionSetName,BMDfoname,showImplant,iRegionSetName,
                    iDensity,stepList,csysName,resGrid,imageNameBase,preferredXraySize,
                    imageFormat,smooth=False,manualImageScaling=False):
    """Creates a virtual CT stack from an ABAQUS odb file. The odb file should contain \n""" + \
    """a step with a fieldoutput variable representing bone mineral density (BMD)"""
        
    # User message
    print '\npyvCT: Create virtual CT plugin'
    
    # Check dependencies
    if not checkDependencies():
        print 'Error: Virtual CT not created\n'
        return
    
    # Process inputs    
    resGrid           = float(resGrid)
    stepList          = [int(s) for s in stepList.replace(',',' ').split()]
    preferredXraySize = int(preferredXraySize)
        
    # Set variables
    dx,dy,dz  = (resGrid,)*3
    iDensity /= 1000.    
    odb       = session.odbs[odbName]
    ec        = dict([(ename,eclass()) for ename,eclass in et.seTypes.items()])

    # Get transformation matrix to convert from global to local coordinate system
    TM = getTMfromCsys(odb,csysName)
    print '\nCT reference frame will be relative to %s' % csysName

    # Get part data and create a bounding box. The bounding box should include the implant if specified
    bRegion,bElemData,bNodeList,bBBox = getPartData(odb,bRegionSetName,TM)
    if showImplant:    
        iRegion,iElemData,iNodeList,iBBox = getPartData(odb,iRegionSetName,TM)
        bbLow = np.min((bBBox[0],iBBox[0]),axis=0)
        bbUpp = np.max((bBBox[1],iBBox[1]),axis=0)
    else:
        bbLow,bbUpp = bBBox
       
    border   = 0.05*(bbUpp-bbLow)
    bbLow    = bbLow - border
    bbUpp    = bbUpp + border
    bbSides  = bbUpp - bbLow
    x0,y0,z0 = bbLow
    xN,yN,zN = bbUpp
    lx,ly,lz = bbSides

    # Generate CT grid
    NX = int(np.ceil(lx/dx+1))
    x  = np.linspace(x0,xN,NX)
    NY = int(np.ceil(ly/dy+1))
    y  = np.linspace(y0,yN,NY)
    NZ = int(np.ceil(lz/dz+1))
    z  = np.linspace(z0,zN,NZ)  
        
    # Create element map for the implant, map to 3D space array and then project onto 3 planes 
    if showImplant: 
        # Get a map for each instance and element type. Then combine maps together
        iElementMap=np.zeros((NX*NY*NZ),dtype=[('inst','|a80'),('cte',int),('g',float),('h',float),('r',float)])
        for instName in iElemData.keys():
            for etype in iElemData[instName].keys():
                edata = iElemData[instName][etype]
                emap  = createElementMap(iNodeList[instName],edata['label'],edata['econn'],ec[etype].numNodes,x,y,z) 
                indx  = np.where(emap['cte']>0)
                iElementMap['inst'][indx] = instName
                iElementMap['cte'][indx]  = emap['cte'][indx]
                iElementMap['g'][indx]    = emap['g'][indx]
                iElementMap['h'][indx]    = emap['h'][indx]
                iElementMap['r'][indx]    = emap['r'][indx]
        # Mask 3D array
        iMask = np.zeros((NX,NY,NZ),dtype=np.float64)   
        for gpi in xrange(iElementMap.size):
            gridPoint = iElementMap[gpi]
            if gridPoint['cte'] > 0:
                i,j,k = convert1Dto3Dindex(gpi,NX,NY,NZ)
                iMask[i,j,k] = iDensity

    # Create the element map for the bone
    bElementMap=np.zeros((NX*NY*NZ),dtype=[('inst','|a80'),('cte',int),('g',float),('h',float),('r',float)])
    for instName in bElemData.keys():
        for etype in bElemData[instName].keys():
            edata = bElemData[instName][etype]
            emap  = createElementMap(bNodeList[instName],edata['label'],edata['econn'],ec[etype].numNodes,x,y,z) 
            indx  = np.where(emap['cte']>0)
            bElementMap['inst'][indx] = instName
            bElementMap['cte'][indx]  = emap['cte'][indx]
            bElementMap['g'][indx]    = emap['g'][indx]
            bElementMap['h'][indx]    = emap['h'][indx]
            bElementMap['r'][indx]    = emap['r'][indx]
    
    # Interpolate HU values from tet mesh onto grid using appropriate tet shape function
    
    # Get frame
    stepId   = stepList[-1]               
    stepName = "Step-%i" % (stepId)
    frame    = odb.steps[stepName].frames[-1]

    # Initialise BMDvalues 
    BMDvalues = dict([(k,{}) for k in bElemData.keys()])         
    for instName,instData in bElemData.items():
        for etype,eData in instData.items():
            for i in xrange(eData.size): 
                BMDvalues[instName][eData[i]['label']] = et.seTypes[etype]()
    
    # Get BMD data for bRegion in frame
    print 'Getting BMDvalues'
    BMDfov = frame.fieldOutputs[BMDfoname].getSubset(region=bRegion, position=ELEMENT_NODAL).values
    cel = 0
    for i in xrange(len(BMDfov)):
        val = BMDfov[i]            
        instanceName = val.instance.name
        elementLabel = val.elementLabel
        if elementLabel!=cel: 
            cel=elementLabel
            indx=0
        else: 
            indx+=1
        BMDvalues[instanceName][elementLabel].setNodalValueByIndex(indx,val.data)

    # Perform the interpolation from elementMap to 3D space array
    print 'Mapping BMD values'
    mappedBMD = np.zeros((NX,NY,NZ),dtype=np.float64)    
    for gpi in xrange(bElementMap.size):
        gridPoint = bElementMap[gpi]
        instName  = gridPoint['inst'] 
        cte       = gridPoint['cte']
        if cte > 0:
            ipc = [gridPoint['g'],gridPoint['h'],gridPoint['r']]
            i,j,k = convert1Dto3Dindex(gpi,NX,NY,NZ)
            mappedBMD[i,j,k] = BMDvalues[instName][cte].interp(ipc)
            
    # Add projected implant to projected bone
    if not showImplant: voxels = mappedBMD
    else:               voxels = mappedBMD + iMask
        
    # Get min/max range of voxel values
    vmin,vmax = [voxels.min(),voxels.max()]
        
    # Scale voxel values to maximum range
    numbits = 16
    low,upp = 0, 2**numbits-1
    voxels  = low + (voxels-vmin)/(vmax-vmin)*upp
    voxels  = np.asarray(voxels,dtype=np.uint16)
    
    # Write CT slices to new directory
    print 'Writing CT slice files'
    # Create a new sub-directory to keep CT slice files
    newSubDirName = 'pyCT'
    newSubDirPath =  os.path.join(os.getcwd(),newSubDirName)
    os.mkdir(newSubDirPath)
    if not os.path.isdir(newSubDirPath):
        print 'Error: Sub-directory %s could not be created' % newSubDirPath
        return
    # Assume stack direction is z-direction. Need to reorder voxel array
    # Note: The array ds.PixelArray is indexed by [row,col], which is equivalent to [yi,xi]. Also,
    # because we are adding to CTvals by z slice, then the resulting index of CTvals is [zi,yi,xi].
    # Correct this to more typical index [xi,yi,zi] by swapping xi and zi e.g. zi,yi,xi -> xi,yi,zi
    voxels = voxels.swapaxes(2,0)
    # Setup basic metadata
    psx = lx/(NX-1)
    psy = ly/(NY-1)
    metaData = {}
    metaData['PixelSpacing'] = ['%.3f' % v for v in (psx,psy)]
    for s in range(voxels.shape[0]):
        sn = ('%5d.dcm' % (s+1)).replace(' ','0')
        fn = os.path.join(newSubDirPath,sn)
        metaData['ImagePositionPatient'] = ['%.3f' % v for v in (x[0],y[0],z[s])]
        pixel_array = voxels[s]
        writeCTslice(pixel_array,fn,metaData)
  
    # User message
    print 'Virtual CT has been created in %s' % newSubDirPath
    print '\nFinished\n'
    
# ~~~~~~~~~~ 

def writeCTslice(pixel_array,filename,metaData):
    
    from dicom.dataset import Dataset, FileDataset

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID =    ''
    file_meta.MediaStorageSOPInstanceUID = ''
    file_meta.ImplementationClassUID =     ''
    ds = FileDataset(filename,{},file_meta = file_meta,preamble="\0"*128)
    ds.SamplesPerPixel = 1                           # 1 for grey scale, 4 for RGBA
    ds.PixelRepresentation = 0                       # 0 for unsigned, 1 for signed
    ds.BitsAllocated = 16                            # 16-bit grey-scale voxel values
    #ds.PhotometricInterpretation = 'MONOCHROME2'    # 0 is black
    ds.Rows    = pixel_array.shape[0]
    ds.Columns = pixel_array.shape[1]
    #ds.ImagePositionPatient = metaData['ImagePositionPatient']
    #ds.PixelSpacing         = metaData['PixelSpacing']
    if pixel_array.dtype != np.uint16:
        pixel_array = pixel_array.astype(np.uint16)
    ds.PixelData = pixel_array.tostring()
    ds.save_as(filename)
    return
    
    