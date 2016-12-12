#
# Copyright 2016 the original author or authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import inspect

import sys
from scapy.fields import ByteField, ShortField, MACField, BitField
from scapy.fields import IntField, StrFixedLenField
from scapy.packet import Packet

from voltha.extensions.omci.omci_defs import OmciUninitializedFieldError, \
    AttributeAccess, OmciNullPointer, EntityOperations
from voltha.extensions.omci.omci_defs import bitpos_from_mask


class EntityClassAttribute(object):

    def __init__(self, fld, access=set(), optional=False):
        self._fld = fld
        self._access = access
        self._optional = optional


class EntityClassMeta(type):
    """
    Metaclass for EntityClass to generate secondary class attributes
    for class attributes of the derived classes.
    """
    def __init__(cls, name, bases, dct):
        super(EntityClassMeta, cls).__init__(name, bases, dct)

        # initialize attribute_name_to_index_map
        cls.attribute_name_to_index_map = dict(
            (a._fld.name, idx) for idx, a in enumerate(cls.attributes))


class EntityClass(object):

    class_id = 'to be filled by subclass'
    attributes = []
    mandatory_operations = {}
    optional_operations = {}

    # will be map of attr_name -> index in attributes, initialized by metaclass
    attribute_name_to_index_map = None
    __metaclass__ = EntityClassMeta

    def __init__(self, **kw):
        assert(isinstance(kw, dict))
        for k, v in kw.iteritems():
            assert(k in self.attribute_name_to_index_map)
        self._data = kw

    def serialize(self, mask=None, operation=None):
        bytes = ''

        # generate ordered list of attribute indices needed to be processed
        # if mask is provided, we use that explicitly
        # if mask is not provided, we determine attributes from the self._data
        # content also taking into account the type of operation in hand
        if mask is not None:
            attribute_indices = EntityClass.attribute_indices_from_mask(mask)
        else:
            attribute_indices = self.attribute_indices_from_data()

        # Serialize each indexed field (ignoring entity id)
        for index in attribute_indices:
            field = self.attributes[index]._fld
            try:
                value = self._data[field.name]
            except KeyError:
                raise OmciUninitializedFieldError(
                    'Entity field "{}" not set'.format(field.name) )
            bytes = field.addfield(None, bytes, value)

        return bytes

    def attribute_indices_from_data(self):
        return sorted(
            self.attribute_name_to_index_map[attr_name]
            for attr_name in self._data.iterkeys())

    byte1_mask_to_attr_indices = dict(
        (m, bitpos_from_mask(m, 8, -1)) for m in range(256))
    byte2_mask_to_attr_indices = dict(
        (m, bitpos_from_mask(m, 16, -1)) for m in range(256))
    @classmethod
    def attribute_indices_from_mask(cls, mask):
        # each bit in the 2-byte field denote an attribute index; we use a
        # lookup table to make lookup a bit faster
        return \
            cls.byte1_mask_to_attr_indices[(mask >> 8) & 0xff] + \
            cls.byte2_mask_to_attr_indices[(mask & 0xff)]

    @classmethod
    def mask_for(cls, *attr_names):
        """
        Return mask value corresponding to given attributes names
        :param attr_names: Attribute names
        :return: integer mask value
        """
        mask = 0
        for attr_name in attr_names:
            index = cls.attribute_name_to_index_map[attr_name]
            mask |= (1 << (16 - index))
        return mask


# abbreviations
ECA = EntityClassAttribute
AA = AttributeAccess
OP = EntityOperations


class OntData(EntityClass):
    class_id = 2
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R}),
        ECA(ByteField("mib_data_sync", 0), {AA.R, AA.W})
    ]
    mandatory_operations = {OP.Get, OP.Set,
                            OP.GetAllAlarms, OP.GetAllAlarmsNext,
                            OP.MibReset, OP.MibUpload, OP.MibUploadNext}
    optional_operations = {}


class CircuitPack(EntityClass):
    class_id = 6
    attributes = [
        ECA(StrFixedLenField("managed_entity_id", None, 22), {AA.R, AA.SBC}),
        ECA(ByteField("type", None), {AA.R, AA.SBC}),
        ECA(ByteField("number_of_ports", None), {AA.R}, optional=True),
        ECA(StrFixedLenField("serial_number", None, 8), {AA.R}),
        ECA(StrFixedLenField("version", None, 14), {AA.R}),
        ECA(StrFixedLenField("vendor_id", None, 4), {AA.R}),
        ECA(ByteField("administrative_state", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("operational_state", None), {AA.R}, optional=True),
        ECA(ByteField("bridged_or_ip_ind", None), {AA.R, AA.W}, optional=True),
        ECA(StrFixedLenField("equipment_id", None, 20), {AA.R}, optional=True),
        ECA(ByteField("card_configuration", None), {AA.R, AA.W, AA.SBC}), # not really mandatory, see spec
        ECA(ByteField("total_tcont_buffer_number", None), {AA.R}),
        ECA(ByteField("total_priority_queue_number", None), {AA.R}),
        ECA(ByteField("total_traffic_scheduler_number", None), {AA.R}),
        ECA(IntField("power_sched_override", None), {AA.R, AA.W},
            optional=True)
    ]
    mandatory_operations = {OP.Get, OP.Set, OP.Reboot}
    optional_operations = {OP.Create, OP.Delete, OP.Test}


class MacBridgeServiceProfile(EntityClass):
    class_id = 45
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ByteField("spanning_tree_ind", False),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ByteField("learning_ind", False), {AA.R, AA.W, AA.SetByCreate}),
        ECA(ByteField("port_bridging_ind", False),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField("priority", None), {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField("max_age", None), {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField("hello_time", None), {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField("forward_delay", None), {AA.R, AA.W, AA.SetByCreate}),
        ECA(ByteField("unknown_mac_address_discard", False),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ByteField("mac_learning_depth", 0),
            {AA.R, AA.W, AA.SetByCreate}, optional=True)

    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.Set}


class MacBridgePortConfigurationData(EntityClass):
    class_id = 47
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ShortField("bridge_id_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("port_num", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("tp_type", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("tp_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("port_priority", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("port_path_cost", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("port_spanning_tree_in", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("encapsulation_methods", None), {AA.R, AA.W, AA.SBC},
            optional=True),
        ECA(ByteField("lan_fcs_ind", None), {AA.R, AA.W, AA.SBC},
            optional=True),
        ECA(MACField("port_mac_address", None), {AA.R}, optional=True),
        ECA(ShortField("outbound_td_pointer", None), {AA.R, AA.W},
            optional=True),
        ECA(ShortField("inbound_td_pointer", None), {AA.R, AA.W},
            optional=True),
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.Set}


class VlanTaggingFilterData(EntityClass):
    class_id = 84
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ShortField("vlan_filter_0", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_1", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_2", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_3", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_4", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_5", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_6", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_7", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_8", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_9", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_10", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("vlan_filter_11", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("forward_operation", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("number_of_entries", None), {AA.R, AA.W, AA.SBC})
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.Set}


class Ieee8021pMapperServiceProfile(EntityClass):
    class_id = 130
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ShortField("tp_pointer", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_0", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_1", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_2", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_3", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_4", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_5", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_6", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField(
            "interwork_tp_pointer_for_p_bit_priority_7", OmciNullPointer),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ByteField("unmarked_frame_option", None),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(StrFixedLenField("dscp_to_p_bit_mapping", None, length=24),
            {AA.R, AA.W}),
        ECA(ByteField("default_p_bit_marking", None),
            {AA.R, AA.W, AA.SetByCreate}),
        ECA(ByteField("tp_type", None), {AA.R, AA.W, AA.SetByCreate},
            optional=True)
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.Set}


class VlanTaggingOperation(Packet):
    name = "VlanTaggingOperation"
    fields_desc = [
        BitField("filter_outer_priority", 0, 4),
        BitField("filter_outer_vid", 0, 13),
        BitField("filter_outer_tpid_de", 0, 3),
        BitField("pad1", 0, 12),

        BitField("filter_inner_priority", 0, 4),
        BitField("filter_inner_vid", 0, 13),
        BitField("filter_inner_tpid_de", 0, 3),
        BitField("pad2", 0, 8),
        BitField("filter_ether_type", 0, 4),

        BitField("treatment_tags_to_remove", 0, 2),
        BitField("pad3", 0, 10),
        BitField("treatment_outer_priority", 0, 4),
        BitField("treatment_outer_vid", 0, 13),
        BitField("treatment_outer_tpid_de", 0, 3),

        BitField("pad4", 0, 12),
        BitField("treatment_inner_priority", 0, 4),
        BitField("treatment_inner_vid", 0, 13),
        BitField("treatment_inner_tpid_de", 0, 3),
    ]


class ExtendedVlanTaggingOperationConfigurationData(EntityClass):
    class_id = 171
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SetByCreate}),
        ECA(ByteField("association_type", None), {AA.R, AA.W, AA.SetByCreate}),
        ECA(ShortField("received_vlan_tagging_operation_table_max_size", None),
            {AA.R}),
        ECA(ShortField("input_tpid", None), {AA.R, AA.W}),
        ECA(ShortField("output_tpid", None), {AA.R, AA.W}),
        ECA(ByteField("downstream_mode", None), {AA.R, AA.W}),
        ECA(StrFixedLenField(
            "received_frame_vlan_tagging_operation_table", None, 16),
        # "received_frame_vlan_tagging_operation_table", None, VlanTaggingOperation),
    {AA.R, AA.W}),
        ECA(ShortField("associated_me_pointer", None), {AA.R, AA.W, AA.SBC})
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Set, OP.Get, OP.GetNext}


class Tcont(EntityClass):
    class_id = 262
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R}),
        ECA(ShortField("alloc_id", 0x00ff), {AA.R, AA.W}),
        ECA(ByteField("mode_indicator", 1), {AA.R}),
        ECA(ByteField("policy", None), {AA.R, AA.W}),  # addendum makes it R/W
    ]
    mandatory_operations = {OP.Get, OP.Set}


class GemInterworkingTp(EntityClass):
    class_id = 266
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SetByCreate}),
        ECA(ShortField("gem_port_network_ctp_pointer", None),
            {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("interworking_option", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("service_profile_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("interworking_tp_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("pptp_counter", None), {AA.R}, optional=True),
        ECA(ByteField("operational_state", None), {AA.R}, optional=True),
        ECA(ShortField("gal_profile_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("gal_loopback_configuration", None),
            {AA.R, AA.W}),
    ]
    mandatory_operations = {}  # TODO


class GemPortNetworkCtp(EntityClass):
    class_id = 268
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ShortField("port_id", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("tcont_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("direction", None), {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("traffic_management_pointer_upstream", None),
            {AA.R, AA.W, AA.SBC}),
        ECA(ShortField("traffic_descriptor_profile_pointer", None),
            {AA.R, AA.W, AA.SBC}, optional=True),
        ECA(ByteField("uni_counter", None), {AA.R}, optional=True),
        ECA(ShortField("priority_queue_pointer_downstream", None),
            {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("encryption_state", None), {AA.R}, optional=True)
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.Set}


class GalEthernetProfile(EntityClass):
    class_id = 272
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ShortField("max_gem_payload_size", None), {AA.R, AA.W, AA.SBC}),
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.Set}


class MulticastGemInterworkingTp(EntityClass):
    class_id = 281
    attributes = [
        ECA(ShortField("managed_entity_id", None), {AA.R, AA.SBC}),
        ECA(ShortField("gem_port_network_ctp_pointer", None), {AA.R, AA.SBC}),
        ECA(ByteField("interworking_option", None), {AA.R, AA.SBC}),
        ECA(ShortField("service_profile_pointer", None), {AA.R, AA.SBC}),
        ECA(ShortField("interworking_tp_pointer", 0), {AA.R, AA.SBC}),
        ECA(ByteField("pptp_counter", None), {AA.R}, optional=True),
        ECA(ByteField("operational_state", None), {AA.R}, optional=True),
        ECA(ShortField("gal_profile_pointer", None), {AA.R, AA.W, AA.SBC}),
        ECA(ByteField("gal_loopback_configuration", None),
            {AA.R, AA.W, AA.SBC}),
        # TODO add multicast_address_table here (page 85 of spec.)
        # ECA(...("multicast_address_table", None), {AA.R, AA.W})
    ]
    mandatory_operations = {OP.Create, OP.Delete, OP.Get, OP.GetNext, OP.Set}


# entity class lookup table from entity_class values
entity_classes_name_map = dict(
    inspect.getmembers(sys.modules[__name__],
    lambda o: inspect.isclass(o) and \
              issubclass(o, EntityClass) and \
              o is not EntityClass)
)

entity_classes = [c for c in entity_classes_name_map.itervalues()]
entity_id_to_class_map = dict((c.class_id, c) for c in entity_classes)