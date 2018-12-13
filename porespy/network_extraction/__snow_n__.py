import scipy as sp
from porespy.network_extraction import regions_to_network
from porespy.network_extraction import add_boundary_regions
from porespy.filters import snow_partitioning
from porespy.tools import make_contiguous
from porespy.metrics import region_surface_areas, region_interface_areas
from collections import namedtuple


def snow_n(im, voxel_size=1,
           boundary_faces=['top', 'bottom', 'left', 'right', 'front', 'back'],
           marching_cubes_area=False,
           return_all=False):

    r"""
    Analyzes an image that has been partitioned into N phase regions
    and extracts all N phases geometerical information alongwith
    network connectivity between any ith and jth phase.

    Parameters
    ----------
    im : ND-array
        Image of porous material where each phase is represented by unique
        integer. Phase integer should start from 1. Boolean image will extract
        only one network labeled with True's only.

    voxel_size : scalar
        The resolution of the image, expressed as the length of one side of a
        voxel, so the volume of a voxel would be **voxel_size**-cubed.  The
        default is 1, which is useful when overlaying the PNM on the original
        image since the scale of the image is alway 1 unit lenth per voxel.

    boundary_faces : list of strings
        Boundary faces labels are provided to assign hypothetical boundary
        nodes having zero resistance to transport process. For cubical
        geometry, the user can choose ‘left’, ‘right’, ‘top’, ‘bottom’,
        ‘front’ and ‘back’ face labels to assign boundary nodes. If no label is
        assigned then all six faces will be selected as boundary nodes
        automatically which can be trimmed later on based on user requirements.

    marching_cubes_area : bool
        If ``True`` then the surface area and interfacial area between regions
        will be using the marching cube algorithm. This is a more accurate
        representation of area in extracted network, but is quite slow, so
        it is ``False`` by default.  The default method simply counts voxels
        so does not correctly account for the voxelated nature of the images.

    return_all : boolean (default is False)
        If set to ``True`` a named tuple is returned containing network dict,
        the original image, the distance transform, the final segmented regions.
        If set to ``False`` it returns network dictionary for all phases.

    Returns
    -------
    A dictionary containing all N phases size data, as well as the
    network topological information.  The dictionary names use the OpenPNM
    convention (i.e. 'pore.coords', 'throat.conns') so it may be converted
    directly to an OpenPNM network object using the ``update`` command.
    """
    # -------------------------------------------------------------------------
    # Perform snow on each phase and merge all segmentation and dt together
    combined_dt = 0
    combined_region = 0
    num = [0]
    phases_num = sp.unique(im*1)
    phases_num = sp.trim_zeros(phases_num)
    for i in phases_num:
        print('_'*60)
        print('### Processing Phase {} ###'.format(i))
        phase_snow = snow_partitioning(im == i, return_all=True)
        if len(phases_num) == 1 and phases_num == 1:
            combined_dt = phase_snow.dt
            combined_region = phase_snow.regions
        else:
            combined_dt += phase_snow.dt
            phase_snow.regions *= phase_snow.im
            phase_snow.regions += num[i-1]
            phase_ws = phase_snow.regions * phase_snow.im
            phase_ws[phase_ws == num[i-1]] = 0
            combined_region += phase_ws
        num.append(sp.amax(combined_region))
    # -------------------------------------------------------------------------
    # Add boundary regions
    f = boundary_faces
    regions = add_boundary_regions(regions=combined_region, faces=f)
    # -------------------------------------------------------------------------
    # Padding distance transform to extract geometrical properties
    if f is not None:
        if im.ndim == 2:
            faces = [(int('left' in f)*3, int('right' in f)*3),
                     (int(('front') in f)*3 or int(('bottom') in f)*3,
                      int(('back') in f)*3 or int(('top') in f)*3)]

        if im.ndim == 3:
            faces = [(int('left' in f)*3, int('right' in f)*3),
                     (int('front' in f)*3, int('back' in f)*3),
                     (int('top' in f)*3, int('bottom' in f)*3)]
        combined_dt = sp.pad(combined_dt, pad_width=faces, mode='edge')
    else:
        combined_dt = combined_dt
    # -------------------------------------------------------------------------
    # For only one phase extraction with boundary regions
    if len(phases_num) == 1 and phases_num == 1:
        if f is not None:
            phase_snow.im = sp.pad(phase_snow.im, pad_width=faces, mode='edge')
        regions = regions*phase_snow.im
        regions = make_contiguous(regions)
    # -------------------------------------------------------------------------
    # Extract N phases sites and bond information from image
    net = regions_to_network(im=regions, dt=combined_dt, voxel_size=voxel_size)
    # -------------------------------------------------------------------------
    # Extract marching cube surface area and interfacial area of regions
    if marching_cubes_area:
        areas = region_surface_areas(regions=regions, voxel_size=voxel_size)
        net['pore.surface_area'] = areas
        interface_area = region_interface_areas(regions=regions, areas=areas,
                                                voxel_size=voxel_size)
        net['throat.area'] = interface_area.area
    # -------------------------------------------------------------------------
    # Find interconnection and interfacial area between ith and jth phases
    conns1 = net['throat.conns'][:, 0]
    conns2 = net['throat.conns'][:, 1]
    label = net['pore.label'] - 1

    for i in phases_num:
        loc1 = sp.logical_and(conns1 >= num[i-1], conns1 < num[i])
        loc2 = sp.logical_and(conns2 >= num[i-1], conns2 < num[i])
        loc3 = sp.logical_and(label >= num[i-1], label < num[i])
        net['throat.phase{}'.format(i)] = loc1 * loc2
        net['pore.phase{}'.format(i)] = loc3
        if i == phases_num[-1]:
            loc4 = sp.logical_and(conns1 < num[-1], conns2 >= num[-1])
            loc5 = label >= num[-1]
            net['throat.boundary'] = loc4
            net['pore.boundary'] = loc5
        for j in phases_num:
            if j > i:
                pi_pj_sa = sp.zeros_like(label)
                loc6 = sp.logical_and(conns2 >= num[j-1], conns2 < num[j])
                pi_pj_conns = loc1 * loc6
                net['throat.phase{}_{}'.format(i, j)] = pi_pj_conns
                if any(pi_pj_conns):
                    # ---------------------------------------------------------
                    # Calculates phase[i] interfacial area that connects with
                    # phase[j] and vice versa
                    p_conns = net['throat.conns'][:, 0][pi_pj_conns]
                    s_conns = net['throat.conns'][:, 1][pi_pj_conns]
                    ps = net['throat.area'][pi_pj_conns]
                    p_sa = sp.bincount(p_conns, ps)
                    # trim zeros at head/tail position to avoid extra bins
                    p_sa = sp.trim_zeros(p_sa)
                    i_index = sp.arange(min(p_conns), max(p_conns)+1)
                    j_index = sp.arange(min(s_conns), max(s_conns)+1)
                    s_pa = sp.bincount(s_conns, ps)
                    s_pa = sp.trim_zeros(s_pa)
                    pi_pj_sa[i_index] = p_sa
                    pi_pj_sa[j_index] = s_pa
                    # ---------------------------------------------------------
                    # Calculates interfacial area using marching cube method
                    if marching_cubes_area:
                        ps_c = net['throat.area'][pi_pj_conns]
                        p_sa_c = sp.bincount(p_conns, ps_c)
                        p_sa_c = sp.trim_zeros(p_sa_c)
                        s_pa_c = sp.bincount(s_conns, ps_c)
                        s_pa_c = sp.trim_zeros(s_pa_c)
                        pi_pj_sa[i_index] = p_sa_c
                        pi_pj_sa[j_index] = s_pa_c
                    net['pore.p{}_{}_area'.format(i, j)] = (pi_pj_sa *
                                                            voxel_size**2)
    # -------------------------------------------------------------------------
    # label boundary cells
    net = label_boundary_cells(network=net, boundary_faces=f)
    # -------------------------------------------------------------------------
    # This code handles the return_all option
    if return_all:
        tup = namedtuple('results', field_names=['net', 'im', 'dt', 'regions'])
        tup.net = net
        tup.im = im.copy()
        tup.dt = combined_dt
        tup.regions = regions
        return tup
    else:
        return net


def label_boundary_cells(network=None, boundary_faces=None):
    r"""
    Takes 2D or 3D network and assign labels to boundary pores

    Parameters
    ----------
    network : 2D or 3D network
        Network should contains nodes coordinates for phase under consideration

    boundary_faces : list of strings
        The user can choose ‘left’, ‘right’, ‘top’, ‘bottom’, ‘front’ and
        ‘back’ face labels to assign boundary nodes. If no label is
        assigned then all six faces will be selected as boundary nodes
        automatically which can be trimmed later on based on user requirements.

    Returns
    -------
    A dictionary containing boundary nodes labels for example
    network['pore.left'], network['pore.right'], network['pore.top'],
    network['pore.bottom'] etc.
    The dictionary names use the OpenPNM convention so it may be converted
    directly to an OpenPNM network object using the ``update`` command.

    """
    f = boundary_faces
    if f is not None:
        coords = network['pore.coords']
        condition = coords[~network['pore.boundary']]
        dic = {'left': 0, 'right': 0, 'front': 1, 'back': 1,
               'top': 2, 'bottom': 2}
        if all(coords[:, 2] == 0):
            dic['top'] = 1
            dic['bottom'] = 1
        for i in f:
            if i in ['left', 'front', 'bottom']:
                network['pore.{}'.format(i)] = (coords[:, dic[i]] <
                                                min(condition[:, dic[i]]))
            elif i in ['right', 'back', 'top']:
                network['pore.{}'.format(i)] = (coords[:, dic[i]] >
                                                max(condition[:, dic[i]]))

    return network